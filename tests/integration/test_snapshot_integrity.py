"""A browser that dies uncleanly leaves its Singleton* links in its
profile, and the next browser started on that profile reads them as
another instance holding it. The profile lives in the home, which
outlives the container's processes, so a restart has to clear them.

Each lock is planted the way Chrome writes it: a symlink whose target
is gone. ``test -e`` follows the link, so the presence check asks
``-L`` as well - without it a planted lock would already count as
cleared.
"""
import shlex
import time

import pytest

from tests.utils import wait_for_log

pytestmark = pytest.mark.requires_image("ag-xfce-kasm")

#: Antigravity IDE 2.6.0 starts the agent's browser with
#: ``--user-data-dir`` here unless the user set another path.
AGENT_PROFILE = ".gemini/antigravity-browser-profile"
LOCKS = ("SingletonLock", "SingletonSocket", "SingletonCookie")
CLEANUP_TIMEOUT = 30

_PLANT = """set -e
mkdir -p "$1"
ln -s "$(hostname)-4242" "$1/SingletonLock"
ln -s /tmp/.stale-browser/SingletonSocket "$1/SingletonSocket"
ln -s 4242424242 "$1/SingletonCookie"
"""
_PRESENT = 'for p in "$@"; do if [ -L "$p" ] || [ -e "$p" ]; then echo "$p"; fi; done'


def _present(docker_cli, name, paths):
    args = " ".join(shlex.quote(p) for p in paths)
    # Checked: an exec that fails prints nothing, which would read as
    # "every lock cleared" while the container is not even running.
    result = docker_cli.run(f"docker exec {name} bash -c {shlex.quote(_PRESENT)} _ {args}")
    return result.stdout.split()


def _plant_locks(docker_cli, name, user, profile):
    """Plant the locks as the sandbox user, whose browser writes them."""
    docker_cli.run(
        f"docker exec -u {user} {name} "
        f"bash -c {shlex.quote(_PLANT)} _ {shlex.quote(profile)}"
    )
    paths = [f"{profile}/{lock}" for lock in LOCKS]
    assert _present(docker_cli, name, paths) == paths, "locks were not planted"
    return paths


def _left_after_restart(docker_cli, name, paths):
    """Restart the container; return the paths it has not cleared within
    CLEANUP_TIMEOUT. Polled: the hooks finish at their own pace, and a
    planted lock can only disappear because the restart removed it."""
    docker_cli.run(f"docker restart {name}")
    deadline = time.monotonic() + CLEANUP_TIMEOUT
    while (left := _present(docker_cli, name, paths)) and time.monotonic() < deadline:
        time.sleep(0.5)
    return left


class TestRestartClearsBrowserLocks:
    def test_entrypoint_clears_agent_profile(self, clean_container, docker_cli, host_env, image):
        """Every connector runs the entrypoint hook, while an ssh image never
        starts the desktop session that sources chrome-cleanup.sh. The hook
        is therefore tested alone, with a command in place of supervisord."""
        name = clean_container("sanity-test-integrity-agent")
        user = host_env["HOST_USER"]
        env_flags = " ".join(f"-e {k}='{v}'" for k, v in host_env.items())
        docker_cli.run(
            f"docker run -d --name {name} {env_flags} {image} "
            "bash -c 'echo sandbox-ready; exec sleep infinity'"
        )
        # The command starts after the last hook, so from here on the
        # first boot's own cleanup cannot remove what is planted next.
        assert wait_for_log(name, "sandbox-ready", timeout=30)

        paths = _plant_locks(docker_cli, name, user, f"/home/{user}/{AGENT_PROFILE}")

        left = _left_after_restart(docker_cli, name, paths)
        assert not left, f"locks survived the restart: {left}"

    def test_desktop_start_clears_browser_profile(self, clean_container, docker_cli, host_env, image):
        """chrome-cleanup.sh runs as the desktop session starts and covers
        the desktop browser's own profile, which the entrypoint does not."""
        name = clean_container("sanity-test-integrity-desktop")
        user = host_env["HOST_USER"]
        docker_cli.run_container(name=name, image=image, env=host_env, rm=False)
        assert wait_for_log(name, "success: kasmvnc", timeout=30)

        # chromium on arm64, Chrome elsewhere: the check the browser
        # wrapper makes, so the profile is the one the browser uses.
        chromium = docker_cli.run(
            f"docker exec {name} test -f /usr/bin/chromium", check=False
        ).returncode == 0
        browser = "chromium" if chromium else "google-chrome"
        paths = _plant_locks(docker_cli, name, user, f"/home/{user}/.config/{browser}")

        left = _left_after_restart(docker_cli, name, paths)
        assert not left, f"locks survived the restart: {left}"
