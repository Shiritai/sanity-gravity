"""``ide`` verb: container-side IDE maintenance.

The agent's manifest declares the maintenance contract in its ``[ide]``
section (see :class:`sanity_gravity.plugins.manifest.IdeSpec`); this
verb only orchestrates the docker cp / exec plumbing around it, so it
works for any agent providing the ``ide`` capability.
"""
from __future__ import annotations

import subprocess

from sanity_gravity.cli.io import (
    print_error,
    print_header,
    print_info,
    print_plain,
)
from sanity_gravity.domain.errors import SanityError
from sanity_gravity.domain.tags import Tag
from sanity_gravity.verbs.lifecycle import find_project_containers, get_active_projects


def ide_cmd(args):
    """Handle deep IDE maintenance inside the container (via gravity-cli)."""
    project_name = getattr(args, "name", "sanity-gravity")
    subcommand = args.ide_command

    active = get_active_projects()
    
    if getattr(args, "name", None) is None:
        if not active:
            print_error("No active managed projects found.")
            print_plain("Tip: Use --name <project> to specify a project.")
            return
        if len(active) > 1:
            print_error(f"Multiple active projects found: {', '.join(active)}")
            print_plain("Please specify a project with --name.")
            return
        project_name = active[0]
    else:
        project_name = args.name

    active = get_active_projects()
    if project_name not in active:
        print_error(f"Project '{project_name}' is not active or managed.")
        return

    matches = find_project_containers(project_name)
    if not matches:
        print_error(f"No running containers found for {project_name}.")
        return
    target_variant = matches[0]["service"]
    container_name = matches[0]["name"]

    from sanity_gravity.core.registry import get_registry
    registry = get_registry()
    # The service label is a boundary string, but a pre-validated one:
    # find_project_containers only yields services in VALID_TAGS, so
    # this parse cannot fail. If it ever does, discovery is broken and
    # a traceback is the honest report.
    agent_slug = Tag.parse(target_variant).agent
    agent_plugin = registry.agents.get(agent_slug)
    
    if not agent_plugin or "ide" not in agent_plugin.provides:
        print_error(f"Agent '{agent_slug}' does not provide an IDE capability.")
        print_error("IDE maintenance commands are not applicable.")
        return

    ide_spec = agent_plugin.ide
    if ide_spec is None:
        print_error(
            f"Agent '{agent_slug}' provides 'ide' but its manifest has "
            "no [ide] section describing the maintenance contract."
        )
        return

    print_header(f"IDE Maintenance ({project_name})")
    print_info(f"Executing {ide_spec.command[0]} {subcommand} in {container_name}...")

    # Refresh the plugin's maintenance tooling inside the (possibly
    # stale) container so old sandboxes stay compatible with the
    # current host checkout. rootfs/ mirrors the container filesystem
    # root, so each rootfs-relative source maps to /<path> in-container.
    print_info("Hot-injecting latest maintenance tooling for compatibility...")
    rootfs = agent_plugin.dir / "rootfs"
    dests = [f"/{rel}" for rel in ide_spec.inject]
    try:
        for rel, dest in zip(ide_spec.inject, dests):
            subprocess.check_call(
                ("docker", "cp", str(rootfs / rel), f"{container_name}:{dest}"),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        if dests:
            subprocess.check_call(
                ("docker", "exec", "-u", "root", container_name,
                 "chmod", "+x", *dests),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
    except subprocess.CalledProcessError as e:
        raise SanityError(
            "Failed to hot-inject maintenance tooling. "
            "Container might be highly incompatible."
        ) from e

    cmd = (
        "docker", "exec", "-it", "-u", "root", container_name,
        *ide_spec.command, subcommand,
    )
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        # Historical contract: any maintenance-command failure ends the
        # process with exit 1 (its own output already reached the tty).
        raise SanityError(
            f"IDE maintenance command failed (exit {e.returncode})."
        ) from e
