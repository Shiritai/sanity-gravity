"""``proxy`` verb: setup / status / remove for the SSH agent socket proxy."""
from __future__ import annotations

from sanity_gravity.cli.io import (
    print_error,
    print_header,
    print_info,
    print_plain,
    print_success,
)
from sanity_gravity.core.colors import Colors
from sanity_gravity.domain.errors import SanityError

try:
    from sanity_gravity.infra.proxy_manager import ProxyManager
except ImportError:  # pragma: no cover - lib is shipped with the repo
    ProxyManager = None


def proxy_setup_cmd(args):
    """Set up the SSH Proxy."""
    if not ProxyManager:
        print_error("ProxyManager library not found.")
        return

    pm = ProxyManager()
    print_header("Setting up SSH Proxy...")
    try:
        pm.setup()
    except (RuntimeError, TimeoutError, OSError, SanityError) as e:
        # Expected setup failures (socat missing, systemd broken,
        # root-owned socket) become a nonzero exit -- the old
        # report-and-return arm exited 0 on a failed setup.
        raise SanityError(f"Setup failed: {e}") from e
    print_success(f"SSH Proxy enabled at {pm.get_socket_path()}")
    print_info("You can now run 'sanity-cli up' to use the proxy.")


def proxy_status_cmd(args):
    """Check SSH Proxy status."""
    if not ProxyManager:
        print_error("ProxyManager library not found.")
        return

    pm = ProxyManager()
    status = pm.get_status()

    print_header("SSH Proxy Status")

    if status["setup"]:
        print_plain(f"  Service:    {Colors.OKGREEN}Enabled{Colors.ENDC}")
    else:
        print_plain(f"  Service:    {Colors.FAIL}Not Setup{Colors.ENDC}")

    if status["active"]:
        print_plain(f"  Active:     {Colors.OKGREEN}Running{Colors.ENDC}")
    else:
        print_plain(f"  Active:     {Colors.FAIL}Stopped{Colors.ENDC}")

    if status["socket_exists"]:
        print_plain(
            f"  Socket:     {Colors.OKGREEN}Present{Colors.ENDC} "
            f"({pm.get_socket_path()})"
        )
    else:
        print_plain(f"  Socket:     {Colors.FAIL}Missing{Colors.ENDC}")

    if status["agent_reachable"]:
        print_plain(f"  Agent:      {Colors.OKGREEN}Reachable{Colors.ENDC}")
    else:
        if status["error"]:
            print_plain(
                f"  Agent:      {Colors.FAIL}Unreachable "
                f"({status['error']}){Colors.ENDC}"
            )
        else:
            print_plain(f"  Agent:      {Colors.FAIL}Unreachable{Colors.ENDC}")


def proxy_remove_cmd(args):
    """Remove the SSH Proxy."""
    if not ProxyManager:
        print_error("ProxyManager library not found.")
        return

    pm = ProxyManager()
    print_header("Removing SSH Proxy...")
    pm.remove()
    print_success("SSH Proxy service and socket removed.")
