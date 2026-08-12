"""``sync_config`` verb: copy project config into running containers.

The :func:`sync_config` helper is also called from the ``up`` flow's
provision phase, so it lives here (not in a private helper) and is
re-exported for that call site.
"""
from __future__ import annotations

import os
import shlex
import shutil
import sys
import time

from sanity_gravity.cli.colors import Colors
from sanity_gravity.cli.io import (
    get_uid_gid_user,
    print_error,
    print_header,
    print_info,
    print_plain,
    print_success,
    print_warning,
    run_command,
)


def sync_config(project_name, container_name, username, config_source="config"):
    """Sync Antigravity configuration to the container."""
    print_header("Configuration Sync")

    config_dir = config_source
    host_gemini_dir = os.path.expanduser("~/.gemini")

    if not os.path.exists(config_dir):
        if not sys.stdin.isatty():
            print_warning(
                "Non-interactive mode detected. Skipping configuration "
                "initialization."
            )
            return

        print_info(f"No project configuration found in ./{config_dir}/")
        print_plain(f"{Colors.BOLD}Select an option to initialize configuration:{Colors.ENDC}")
        print_plain("  [A] Copy from Host (~/.gemini/) - Recommended")
        print_plain("  [B] Create Empty (Initialize empty config)")
        print_plain("  [C] Skip (Use container defaults)")

        choice = input(
            f"{Colors.OKBLUE}Enter choice [A/b/c]: {Colors.ENDC}"
        ).strip().lower()

        if choice in ["", "a"]:
            print_info("Copying configuration from host...")
            os.makedirs(config_dir, exist_ok=True)

            src_gemini = os.path.join(host_gemini_dir, "GEMINI.md")
            if os.path.exists(src_gemini):
                shutil.copy2(src_gemini, os.path.join(config_dir, "GEMINI.md"))
                print_success("Copied GEMINI.md")
            else:
                print_warning("Host GEMINI.md not found, skipping.")

            src_settings = os.path.join(host_gemini_dir, "settings.json")
            if os.path.exists(src_settings):
                shutil.copy2(src_settings, os.path.join(config_dir, "settings.json"))
                print_success("Copied settings.json")

        elif choice == "b":
            print_info("Creating empty configuration...")
            os.makedirs(config_dir, exist_ok=True)
            with open(os.path.join(config_dir, "GEMINI.md"), "w") as f:
                f.write("# Project GEMINI.md\n")
            with open(os.path.join(config_dir, "settings.json"), "w") as f:
                f.write("{}")
            print_success("Created empty config files.")

        else:
            print_info("Skipping configuration sync.")
            return

    if os.path.exists(config_dir):
        print_info(f"Syncing ./config/ to container ({container_name})...")

        user_ready = False
        for _ in range(30):
            out = run_command(
                ("docker", "exec", container_name, "id", "-u", username),
                capture=True, check=False,
            )
            if out and out.strip().isdigit():
                user_ready = True
                break
            time.sleep(1)

        if not user_ready:
            print_warning(
                f"User '{username}' not found in container after 30s. "
                "Sync might fail."
            )

        target_dir = f"/home/{username}/.gemini"

        run_command(
            ("docker", "exec", container_name, "mkdir", "-p", target_dir)
        )

        print_info("Transferring files (excluding runtime state)...")
        # Genuine shell requirement: this is a pipe between two processes.
        # All interpolated values are quoted with shlex.quote as defence-in-depth.
        tar_cmd = (
            f"tar -cf - -C {shlex.quote(config_dir)} "
            f"--exclude='antigravity/daemon' "
            f"--exclude='antigravity-browser-profile' . "
            f"| docker exec -i {shlex.quote(container_name)} "
            f"tar -xf - -C {shlex.quote(target_dir)}"
        )
        run_command(tar_cmd, shell=True)

        out = run_command(
            ("docker", "exec", container_name, "chown", "-R",
             f"{username}:{username}", target_dir),
            capture=True, check=False,
        )
        if out:
            print_warning(
                f"Failed to set permissions on {target_dir}: {out} "
                "(User mismatch?)"
            )

        print_success("Configuration synced successfully.")


def sync_config_cmd(args):
    """Sync configuration to running containers without restarting."""
    # Lazy import to avoid the circular dep with status.get_active_projects /
    # upgrade.get_project_env that all live in lifecycle modules.
    from sanity_gravity.verbs.lifecycle import (
        find_project_containers,
        get_active_projects,
        get_project_env,
    )

    target_project = getattr(args, "name", "sanity-gravity")

    projects_to_sync = []
    if target_project == "sanity-gravity":
        projects_to_sync = get_active_projects()
        if not projects_to_sync:
            print_info("No active managed projects found to sync.")
            return
    else:
        active = get_active_projects()
        if target_project in active:
            projects_to_sync = [target_project]
        else:
            print_error(f"Project '{target_project}' is not active or managed.")
            return

    print_header("Syncing Configuration")

    host_uid, host_gid, host_user = get_uid_gid_user()

    for project in projects_to_sync:
        try:
            env_vars = get_project_env(project)
            username = env_vars.get("HOST_USER", host_user)

            matches = find_project_containers(project)
            if matches:
                container_name = matches[0]["name"]
                print_info(f"Syncing {project} ({container_name})...")
                sync_config(project, container_name, username)
            else:
                print_warning(
                    f"Project {project} has no running containers. Skipping."
                )

        except Exception as e:
            print_error(f"Failed to sync {project}: {e}")

    print_success("Sync complete.")
