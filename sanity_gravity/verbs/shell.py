"""``shell`` verb: exec into a running sandbox container."""
from __future__ import annotations

import subprocess

from sanity_gravity.cli.io import (
    print_error,
    print_info,
    print_warning,
)
from sanity_gravity.verbs.lifecycle import (
    find_project_containers,
    get_active_projects,
    get_project_env,
)


def shell_cmd(args):
    """Exec into the shell of a running container."""
    project_name = args.name

    if project_name == "sanity-gravity":
        active = get_active_projects()
        if not active:
            print_error("No active projects found.")
            return
        if len(active) > 1:
            print_info(f"Multiple active projects: {', '.join(active)}")
            print_warning(f"Defaulting to first active project: {active[0]}")
            project_name = active[0]
        else:
            project_name = active[0]

    matches = find_project_containers(project_name)
    if not matches:
        print_error(f"No running containers found for {project_name}.")
        return
    container_name = matches[0]["name"]

    env = get_project_env(project_name)
    user = args.user if args.user else env.get("HOST_USER", "developer")

    print_info(f"Entering shell for {project_name} ({container_name}) as {user}...")

    if 'use' not in args:
        shell = 'zsh'
        fallback_to_bash = True
    else:
        shell = args.use
        fallback_to_bash = False

    cmd = ("docker", "exec", "-it", "-u", user, container_name, shell)
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError:
        if fallback_to_bash:
            print_warning(f"{shell} failed, falling back to bash...")
            cmd = ("docker", "exec", "-it", "-u", user, container_name, "bash")
            subprocess.call(cmd)
        else:
            print_error(
                f"{shell} failed. Specify the --use parameter to pick another shell."
            )
