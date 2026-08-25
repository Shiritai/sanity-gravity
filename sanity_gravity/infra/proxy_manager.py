"""SSH Agent Proxy service management (systemd user unit + socat).

Subprocess policy: systemctl probes go through
:func:`sanity_gravity.core.proc.try_run` and are matched explicitly --
"not enabled" / "not active" is the domain answer for ANY non-zero
outcome, including rc=127 on hosts without systemd, where the proxy
genuinely is not set up. Steps that must succeed escalate with
``raise_for_status`` (a typed CommandError instead of the historical
DEVNULL-swallowed check_call).
"""
from __future__ import annotations

import os
import shutil
import time

from sanity_gravity.core.proc import try_run


class ProxyManager:
    """
    Manages the SSH Agent Proxy service.

    This class handles the creation, monitoring, and removal of a systemd
    user service that bridges the host's SSH Agent to a fixed path for
    container consumption.
    """

    def __init__(self):
        self.home = os.path.expanduser("~")
        self.gemini_dir = os.path.join(self.home, ".gemini")
        self.bridge_dir = os.path.join(self.gemini_dir, "bridge")
        self.socket_path = os.path.join(self.bridge_dir, "ssh.sock")
        self.service_name = "sanity-gravity-proxy"
        self.unit_file_path = os.path.join(
            self.home, ".config/systemd/user", f"{self.service_name}.service",
        )

    def check_prerequisites(self):
        """Checks if socat is installed."""
        return bool(shutil.which("socat"))

    def get_socket_path(self):
        """Returns the fixed socket path."""
        return self.socket_path

    def is_enabled(self):
        """Checks if the proxy service is set up (unit file exists and enabled)."""
        # Simple check: Is the service file there?
        if not os.path.exists(self.unit_file_path):
            return False

        # Explicit match: only the literal "enabled" answer counts.
        # Disabled units, broken systemd, and systemd-less hosts all
        # mean the proxy is not usable-as-enabled.
        res = try_run(
            ["systemctl", "--user", "is-enabled", self.service_name],
        )
        return res.stdout == "enabled"

    def get_status(self):
        """Returns status dict: active, socket_exists, agent_reachable, error"""
        status = {
            "setup": self.is_enabled(),
            "active": False,
            "socket_exists": os.path.exists(self.socket_path),
            "agent_reachable": False,
            "error": None,
        }

        if status["setup"]:
            res = try_run(
                ["systemctl", "--user", "is-active", self.service_name],
            )
            status["active"] = res.stdout == "active"

        # Check Agent Reachability (if socket exists)
        if status["socket_exists"]:
            try:
                # Try to list keys via the bridge socket. try_run merges
                # the env mapping over os.environ, so only the override
                # is spelled here.
                #
                # ssh-add -l returns:
                # 0: Success (Has keys)
                # 1: Success (No keys)
                # 2: Error (Connection Refused / File not found etc)
                # 127 is try_run's answer for a missing ssh-add binary;
                # it lands in the unreachable branch below, still
                # error-as-data.
                res = try_run(
                    ["ssh-add", "-l"],
                    env={"SSH_AUTH_SOCK": self.socket_path},
                )

                if res.returncode in [0, 1]:
                    status["agent_reachable"] = True
                else:
                    # Connection refused usually prints to stderr
                    err_msg = res.stderr.strip() or "Unknown error"
                    status["error"] = (
                        f"Agent unreachable (Code {res.returncode}): {err_msg}"
                    )

            except OSError as e:
                # error-as-data on purpose: get_status feeds the status
                # verb's rendering and must never crash it. A missing
                # ssh-add binary never lands here (try_run maps it to
                # rc=127, reported above); this arm covers the launch
                # failures subprocess.run can still raise, e.g. a
                # PermissionError on a non-executable ssh-add.
                status["error"] = f"Error verifying agent: {e}"

        return status

    def setup(self):
        """Sets up the systemd service."""
        if not self.check_prerequisites():
            raise RuntimeError(
                "socat is not installed. Please install it "
                "(e.g. `sudo apt install socat`)."
            )

        # 1. Prepare Directories
        # We need to remove the socket file if it exists (stale) to let
        # socat create it.
        if os.path.exists(self.socket_path):
            try:
                if os.path.isdir(self.socket_path):
                    shutil.rmtree(self.socket_path)
                else:
                    os.remove(self.socket_path)
            except OSError as e:
                # If we fail to remove it, it might be root owned
                # (common Docker issue).
                if os.path.isdir(self.socket_path):
                    raise RuntimeError(
                        f"Conflict: '{self.socket_path}' is a directory and "
                        "cannot be removed.\n"
                        "This often happens when Docker automatically creates "
                        "a directory for a missing volume source.\n"
                        f"Please run: sudo rm -rf {self.socket_path}"
                    ) from e

        os.makedirs(self.bridge_dir, exist_ok=True)
        os.makedirs(os.path.dirname(self.unit_file_path), exist_ok=True)

        # 2. Create Unit File. The service runs in user session scope and
        # inherits SSH_AUTH_SOCK from the desktop environment;
        # ``unlink-early`` makes socat replace a stale socket on start.
        socat_bin = shutil.which("socat")
        if not socat_bin:
            raise RuntimeError("socat not found in PATH")

        unit_content = f"""[Unit]
Description=SSH Agent Socket Proxy for Sanity Gravity
After=ssh-agent.service

[Service]
ExecStart=/bin/sh -c 'exec {socat_bin} UNIX-LISTEN:{self.socket_path},fork,unlink-early UNIX-CONNECT:$SSH_AUTH_SOCK'
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
"""
        with open(self.unit_file_path, "w") as f:
            f.write(unit_content)

        # 3. Reload and Enable. These must succeed: a failure raises
        # CommandError (with systemctl's stderr) instead of vanishing
        # into DEVNULL as the old check_call plumbing did.
        for action in ("daemon-reload", None), ("enable", self.service_name), \
                      ("restart", self.service_name):
            argv = ["systemctl", "--user", action[0]]
            if action[1]:
                argv.append(action[1])
            try_run(argv).raise_for_status()

        # Verify and Wait for Socket
        for _ in range(10):
            if os.path.exists(self.get_socket_path()):
                return
            time.sleep(1)

        # If loop finishes, check if service is at least active
        if not self.get_status()["active"]:
            raise RuntimeError(
                "Service failed to start. Check "
                "'systemctl --user status sanity-gravity-proxy'"
            )

        raise TimeoutError(
            f"Service is active but socket failed to appear at "
            f"{self.get_socket_path()}"
        )

    def remove(self):
        """Removes the systemd service."""
        # Stop and Disable. Best-effort on purpose: a service systemd no
        # longer knows about must not block the file cleanup below.
        if self.is_enabled():
            try_run(
                ["systemctl", "--user", "disable", "--now", self.service_name],
            )

        # Remove Unit File
        if os.path.exists(self.unit_file_path):
            os.remove(self.unit_file_path)
            try_run(["systemctl", "--user", "daemon-reload"]).raise_for_status()

        # Clean Socket
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)
        # Wait for socket to be removed by socat or systemd
        for _ in range(10):
            if not os.path.exists(self.get_socket_path()):
                return
            time.sleep(1)

        # If the loop finishes, the socket still exists: removal failed.
        raise TimeoutError(
            f"Socket failed to be removed at {self.get_socket_path()}"
        )
