"""``ide`` verb: container-side IDE maintenance.

The agent's manifest declares the maintenance contract in its ``[ide]``
section (see :class:`sanity_gravity.plugins.manifest.IdeSpec`); this
verb only orchestrates the docker cp / exec plumbing around it, so it
works for any agent providing the ``ide`` capability.
"""
from __future__ import annotations

import subprocess

from sanity_gravity.cli.io import (
    print_header,
    print_info,
)
from sanity_gravity.domain.errors import SanityError
from sanity_gravity.verbs.lifecycle import find_project_containers, get_active_projects


def ide_cmd(args):
    """Handle deep IDE maintenance inside the container (via gravity-cli)."""
    project_name = getattr(args, "name", "sanity-gravity")
    subcommand = args.ide_command

    active = get_active_projects()
    
    if getattr(args, "name", None) is None:
        if not active:
            raise SanityError(
                "No active managed projects found.",
                hint="Use --name <project> to specify a project.",
            )
        if len(active) > 1:
            raise SanityError(
                f"Multiple active projects found: {', '.join(active)}",
                hint="Please specify a project with --name.",
            )
        project_name = active[0]
    else:
        project_name = args.name

    # A precondition failure must raise: print_error + return would end
    # the process with exit 0 (the dispatcher drops the return value).
    active = get_active_projects()
    if project_name not in active:
        raise SanityError(f"Project '{project_name}' is not active or managed.")

    matches = find_project_containers(project_name)
    if not matches:
        raise SanityError(f"No running containers found for {project_name}.")
    target_tag = matches[0]["tag"]
    container_name = matches[0]["name"]

    from sanity_gravity.core.registry import get_registry
    registry = get_registry()
    # Discovery already parsed the service label; read the value.
    agent_slug = target_tag.agent
    agent_plugin = registry.agents.get(agent_slug)
    
    if not agent_plugin or "ide" not in agent_plugin.provides:
        raise SanityError(
            f"Agent '{agent_slug}' does not provide an IDE capability.",
            hint="IDE maintenance commands are not applicable.",
        )

    ide_spec = agent_plugin.ide
    if ide_spec is None:
        raise SanityError(
            f"Agent '{agent_slug}' provides 'ide' but its manifest has "
            "no [ide] section describing the maintenance contract."
        )

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
