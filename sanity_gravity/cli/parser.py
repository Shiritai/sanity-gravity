"""Argparse setup for sanity-cli.

Each verb gets its own ``add_*_parser(subparsers)`` function. The
top-level :func:`build_parser` wires them together. ``main()`` simply
calls :func:`build_parser` and dispatches on ``args.func``.
"""
from __future__ import annotations

import argparse

from sanity_gravity.cli.registry import DEFAULT_TAG
from sanity_gravity.verbs.build import build
from sanity_gravity.verbs.check import check_prereqs
from sanity_gravity.verbs.ide import ide_cmd
from sanity_gravity.verbs.lifecycle import clean, down, restart, start, stop
from sanity_gravity.verbs.open import open_cmd
from sanity_gravity.verbs.proxy import (
    proxy_remove_cmd,
    proxy_setup_cmd,
    proxy_status_cmd,
)
from sanity_gravity.verbs.shell import shell_cmd
from sanity_gravity.verbs.snapshot import snapshot_cmd
from sanity_gravity.verbs.status import list_variants, plugins_list, status
from sanity_gravity.verbs.sync import sync_config_cmd
from sanity_gravity.verbs.pull import pull
from sanity_gravity.verbs.test_suite import test_suite
from sanity_gravity.verbs.up import up
from sanity_gravity.verbs.upgrade import upgrade


def _add_up_args(p):
    """Shared up/run/explain-up arguments."""
    p.add_argument(
        "--variant", "-v", required=True,
        help=f"Tag to run (e.g. {DEFAULT_TAG})",
    )
    p.add_argument("--ssh-port", "-p", default="2222",
                   help="Host port for SSH (default: 2222)")
    p.add_argument("--kasm-port", default="8444",
                   help="Host port for KasmVNC (default: 8444)")
    p.add_argument("--vnc-port", default="5901",
                   help="Host port for VNC (default: 5901)")
    p.add_argument("--novnc-port", default="6901",
                   help="Host port for noVNC (default: 6901)")
    p.add_argument("--password", default="antigravity",
                   help="Password for SSH/VNC (default: antigravity)")
    p.add_argument("--skip-check", action="store_true",
                   help="Skip prerequisite checks")
    p.add_argument("--workspace", "-w", default=None,
                   help="Path to workspace directory (default: ./workspace)")
    p.add_argument("--name", "-n", default="sanity-gravity",
                   help="Project name for multi-instance support "
                        "(default: sanity-gravity)")
    p.add_argument("--cpus", default=None, help="CPU limit (e.g. 1.5)")
    p.add_argument("--memory", default=None, help="Memory limit (e.g. 4G)")
    p.add_argument("--image", default=None,
                   help="Use custom base image (Snapshot)")
    p.add_argument("--recreate", action="store_true",
                   help="Force recreate if sandbox already exists")
    p.add_argument("--pull", action="store_true",
                   help="Force pull the latest image from GHCR before starting")
    p.set_defaults(func=up)


def build_parser():
    """Build the top-level argparse parser, wired up with every verb."""
    parser = argparse.ArgumentParser(description="Antigravity Sandbox CLI")
    parser.add_argument(
        "--log-format",
        choices=["text", "json"],
        default="text",
        help=(
            "Output format (must precede subcommand). 'text' = ANSI on stdout "
            "(default). 'json' = JSONL narration on stderr; data still on stdout."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Plan side effects without executing them. Each Action is "
            "rendered as a 'would: ...' line; no Docker / FS calls are made."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # check
    p_check = subparsers.add_parser("check", help="Check prerequisites")
    p_check.set_defaults(func=check_prereqs)

    # build
    p_build = subparsers.add_parser("build", help="Build sandbox images")
    p_build.add_argument(
        "variant", nargs="*",
        help="Tag to build, e.g. ag-xfce-kasm (default: all)",
        default=["all"],
    )
    p_build.add_argument("--no-cache", action="store_true",
                         help="Do not use cache when building image")
    p_build.add_argument("--layer", choices=["base", "desktop", "agent", "connector"],
                         help="Build only up to a specific layer (CI use)")
    p_build.add_argument("--layer-target",
                         help="Specific target within --layer (e.g. xfce, ag-xfce)")
    p_build.add_argument("--list-intermediates", action="store_true",
                         help="List intermediate image names and exit")
    p_build.add_argument("--json", dest="json_output", action="store_true",
                         help="Output in JSON format (for --list-intermediates)")
    p_build.set_defaults(func=build)

    # up
    p_up = subparsers.add_parser(
        "up", help="Create and start sandbox (docker compose up)"
    )
    _add_up_args(p_up)


    # down
    p_down = subparsers.add_parser(
        "down", help="Stop and remove containers (docker compose down)"
    )
    p_down.add_argument("--name", "-n", default="sanity-gravity",
                        help="Project name (default: sanity-gravity)")
    p_down.set_defaults(func=down)

    # clean
    p_clean = subparsers.add_parser(
        "clean", help="Deep cleanup: remove containers, volumes and local images"
    )
    p_clean.add_argument("--name", "-n", default="sanity-gravity",
                         help="Project name (default: sanity-gravity)")
    p_clean.add_argument("--force", "-f", action="store_true",
                         help="Force cleanup without confirmation")
    p_clean.set_defaults(func=clean)

    # stop
    p_stop = subparsers.add_parser(
        "stop", help="Stop containers without removing (docker compose stop)"
    )
    p_stop.add_argument("--name", "-n", default="sanity-gravity",
                        help="Project name (default: sanity-gravity)")
    p_stop.set_defaults(func=stop)

    # start
    p_start = subparsers.add_parser(
        "start", help="Start stopped containers (docker compose start)"
    )
    p_start.add_argument("--name", "-n", default="sanity-gravity",
                         help="Project name (default: sanity-gravity)")
    p_start.set_defaults(func=start)

    # restart
    p_restart = subparsers.add_parser(
        "restart", help="Restart containers (docker compose restart)"
    )
    p_restart.add_argument("--name", "-n", default="sanity-gravity",
                           help="Project name (default: sanity-gravity)")
    p_restart.set_defaults(func=restart)

    # status
    p_status = subparsers.add_parser("status", help="Show sandbox status")
    p_status.add_argument("--name", "-n", default="sanity-gravity",
                          help="Project name (default: sanity-gravity)")
    p_status.set_defaults(func=status)

    # list
    p_list = subparsers.add_parser(
        "list", help="List available tags and dimension matrix"
    )
    p_list.add_argument("--json", dest="json_output", action="store_true",
                        help="Output valid tags as JSON array")
    p_list.set_defaults(func=list_variants)

    # upgrade
    p_upgrade = subparsers.add_parser(
        "upgrade",
        help="[Legacy] Upgrade legacy containers to managed status (Host Side Only)",
    )
    p_upgrade.add_argument("--name", "-n", default="sanity-gravity",
                           help="Specific project to upgrade")
    p_upgrade.set_defaults(func=upgrade)

    # sync_config
    p_sync = subparsers.add_parser(
        "sync_config", help="Sync configuration to running containers"
    )
    p_sync.add_argument("--name", "-n", default="sanity-gravity",
                        help="Specific project to sync")
    p_sync.set_defaults(func=sync_config_cmd)

    # shell
    p_shell = subparsers.add_parser("shell", help="Enter container shell")
    p_shell.add_argument("--name", "-n", default="sanity-gravity",
                         help="Project name")
    p_shell.add_argument("--user", "-u", default=None,
                         help="User to login as (default: developer)")
    p_shell.add_argument(
        "--use", default=argparse.SUPPRESS, choices=["zsh", "bash"],
        help="Shell to use (default: zsh, with fallback to bash)",
    )
    p_shell.set_defaults(func=shell_cmd)

    # pull
    p_pull = subparsers.add_parser("pull", help="Pull sandbox images from GHCR")
    p_pull.add_argument(
        "variant", nargs="*",
        help="Tag to pull, e.g. ag-xfce-kasm (default: all)",
        default=["all"],
    )
    p_pull.add_argument(
        "--tag", default=None,
        help="Explicit version tag to pull (default: auto-detected from git)",
    )
    p_pull.set_defaults(func=pull)

    # open
    p_open = subparsers.add_parser("open", help="Open web interface")
    p_open.add_argument("--name", "-n", default="sanity-gravity",
                        help="Project name")
    p_open.set_defaults(func=open_cmd)

    # snapshot
    p_snapshot = subparsers.add_parser(
        "snapshot", help="Create a perfect copy (snapshot) of a container"
    )
    p_snapshot.add_argument("--name", "-n", default="sanity-gravity",
                            help="Project name")
    p_snapshot.add_argument(
        "--variant", "-v", default=None,
        help="Tag to snapshot (optional if only one running)",
    )
    p_snapshot.add_argument(
        "--tag", "-t", required=True,
        help="Tag for the new image (e.g. my-backup:v1)",
    )
    p_snapshot.set_defaults(func=snapshot_cmd)

    # plugins
    p_plugins = subparsers.add_parser(
        "plugins",
        help="Inspect manifest-driven plugins (agents/desktops/connectors)",
    )
    plugins_subparsers = p_plugins.add_subparsers(
        dest="plugins_command", required=True,
    )
    plugins_list_p = plugins_subparsers.add_parser(
        "list", help="List registered plugins (kind, slug, capabilities, ports)",
    )
    plugins_list_p.set_defaults(func=plugins_list)

    # proxy
    p_proxy = subparsers.add_parser("proxy", help="Manage SSH Agent Socket Proxy")
    proxy_subparsers = p_proxy.add_subparsers(
        dest="proxy_command", required=True,
    )
    proxy_setup = proxy_subparsers.add_parser(
        "setup", help="Setup and enable SSH Proxy",
    )
    proxy_setup.set_defaults(func=proxy_setup_cmd)
    proxy_status = proxy_subparsers.add_parser(
        "status", help="Check SSH Proxy status",
    )
    proxy_status.set_defaults(func=proxy_status_cmd)
    proxy_remove = proxy_subparsers.add_parser(
        "remove", help="Disable and remove SSH Proxy",
    )
    proxy_remove.set_defaults(func=proxy_remove_cmd)

    # ide
    p_ide = subparsers.add_parser(
        "ide", help="Container-side Antigravity IDE Maintenance",
    )
    p_ide.add_argument("--name", "-n", default="sanity-gravity",
                       help="Project name (default: sanity-gravity)")
    ide_subparsers = p_ide.add_subparsers(dest="ide_command", required=True)

    ide_update = ide_subparsers.add_parser(
        "update", help="Update the IDE to the latest package version via apt",
    )
    ide_update.add_argument("--name", "-n", default="sanity-gravity",
                            help="Project name")
    ide_update.set_defaults(func=ide_cmd, ide_command="update")

    ide_reinstall = ide_subparsers.add_parser(
        "reinstall", help="Cleanly purge and reinstall the IDE to fix crashes",
    )
    ide_reinstall.add_argument("--name", "-n", default="sanity-gravity",
                               help="Project name")
    ide_reinstall.set_defaults(func=ide_cmd, ide_command="reinstall")

    # test
    p_test = subparsers.add_parser("test", help="Run test suite")
    p_test.add_argument(
        "target", nargs="?",
        help="Specific test target (e.g., tests/test_core.py)",
    )
    p_test.set_defaults(func=test_suite)

    # NOTE: ``explain`` is *not* a subparser. It is rewritten to
    # ``--dry-run`` by ``cli.main._preprocess_argv`` so any verb can be
    # explained — read-only verbs ignore the flag, kernelized verbs
    # honor it. See main.py for the rewrite logic.

    return parser
