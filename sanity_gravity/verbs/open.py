"""``open`` verb: open the running project's web interface in a browser."""
from __future__ import annotations

import subprocess
import webbrowser

from sanity_gravity.cli.io import (
    print_error,
    print_success,
    print_warning,
    run_command,
)
from sanity_gravity.cli.registry import parse_tag
from sanity_gravity.verbs.lifecycle import find_project_containers, get_active_projects


def open_cmd(args):
    """Open the active project's web interface."""
    project_name = args.name

    if project_name == "sanity-gravity":
        active = get_active_projects()
        if not active:
            print_error("No active projects found.")
            return
        project_name = active[0]

    matches = find_project_containers(project_name)
    if not matches:
        print_error(f"No running containers found for {project_name}.")
        return
    target_variant = matches[0]["service"]

    url = None

    def resolve_port(service, internal):
        try:
            out = run_command(
                ("docker", "compose", "-p", project_name,
                 "port", service, str(internal)),
                capture=True, check=False,
            )
            if ":" in out:
                return out.split(":")[-1]
        except subprocess.CalledProcessError as e:
            print_warning(f"Could not resolve {service}:{internal} port ({e})")
        return None

    try:
        _, _, connector = parse_tag(target_variant)
    except ValueError:
        connector = None

    if connector == "kasm":
        port = resolve_port(target_variant, "8444")
        if port:
            url = f"https://localhost:{port}"
    elif connector == "vnc":
        port = resolve_port(target_variant, "6901")
        if port:
            url = f"http://localhost:{port}/vnc.html"
    elif connector == "ssh":
        print_warning(f"Variant '{target_variant}' has no web interface (SSH only).")
        return

    if url:
        print_success(f"Opening {url} ...")
        webbrowser.open(url)
    else:
        print_error("Could not resolve accessible URL.")
