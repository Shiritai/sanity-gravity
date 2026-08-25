"""``open`` verb: open the running project's web interface in a browser."""
from __future__ import annotations

import webbrowser

from sanity_gravity.cli.io import (
    print_error,
    print_success,
    print_warning,
)
from sanity_gravity.core.proc import try_run
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
    target_tag = matches[0]["tag"]

    url = None

    def resolve_port(service, internal):
        res = try_run(
            ("docker", "compose", "-p", project_name,
             "port", service, str(internal)),
        )
        if not res.ok:
            # The rc distinguishes "docker broke" from "nothing bound";
            # the old except-CalledProcessError arm here was dead code
            # (check=False never raised) so this warning never fired.
            print_warning(
                f"Could not resolve {service}:{internal} port "
                f"({res.stderr or f'exit {res.returncode}'})"
            )
            return None
        if ":" in res.stdout:
            return res.stdout.split(":")[-1]
        return None

    # Discovery already parsed the service label; read the value.
    connector = target_tag.connector

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
