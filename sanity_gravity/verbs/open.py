"""``open`` verb: open the running project's web interface in a browser."""
from __future__ import annotations

import subprocess
import webbrowser

from sanity_gravity.cli.io import (
    print_error,
    print_info,
    print_success,
    print_warning,
    run_command,
)
from sanity_gravity.cli.registry import VALID_TAGS, parse_tag
from sanity_gravity.verbs.lifecycle import get_active_projects


def open_cmd(args):
    """Open the active project's web interface."""
    project_name = args.name

    if project_name == "sanity-gravity":
        active = get_active_projects()
        if not active:
            print_error("No active projects found.")
            return
        project_name = active[0]

    target_variant = None
    container_name = None
    for v in VALID_TAGS:
        cname = f"{project_name}-{v}-1"
        try:
            out = run_command(
                ("docker", "inspect", "-f", "{{.State.Running}}", cname),
                capture=True, check=False,
            )
            if out == "true":
                target_variant = v
                container_name = cname
                break
        except subprocess.CalledProcessError:
            pass

    if not container_name:
        print_error(f"No running containers found for {project_name}.")
        return

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
        _, _, _, connector = parse_tag(target_variant)
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
