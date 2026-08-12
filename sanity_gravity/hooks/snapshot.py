"""Builtin hooks for the ``snapshot`` verb.

Phase split:
- ``SNAPSHOT_PLAN`` — locate the running container (handle the
  multi-variant prompt), populate ``ctx.container_id``.
- ``SNAPSHOT_DOCKER`` — enqueue ``docker commit <container> <tag>``.
- ``SNAPSHOT_DONE`` — emit success + a copy-pasteable usage hint.
"""
from __future__ import annotations

import sys

from sanity_gravity.cli.colors import Colors
from sanity_gravity.cli.io import run_command
from sanity_gravity.core.eventbus import EventBus, get_default_bus
from sanity_gravity.domain.phase import Phase
from sanity_gravity.effects.actions import RunSubprocess


def _container_exists(name: str) -> bool:
    out = run_command(("docker", "inspect", name), capture=True, check=False)
    return bool(out and out.strip() and out.strip() != "[]")


def snapshot_resolve_project(ctx) -> None:
    """SNAPSHOT_PLAN/50: if project=='sanity-gravity', auto-pick the only active one."""
    if ctx.project != "sanity-gravity":
        return
    if ctx.dry_run:
        return  # don't touch docker in dry-run
    from sanity_gravity.verbs.lifecycle import get_active_projects

    active = get_active_projects()
    if not active:
        ctx.reporter.error("No active projects found.")
        print("Tip: Use --name <project> to specify a project.")
        ctx.cancelled = True
        return
    if len(active) > 1:
        ctx.reporter.error(f"Multiple active projects found: {', '.join(active)}")
        print("Please specify a project with --name.")
        ctx.cancelled = True
        return
    ctx.project = active[0]


def snapshot_resolve_container(ctx) -> None:
    """SNAPSHOT_PLAN/100: pick the container_id (with multi-variant prompt)."""
    if ctx.cancelled:
        return
    if ctx.dry_run:
        # In dry-run, fabricate a placeholder so the planned commit can render.
        v = ctx.variant or "<variant>"
        ctx.target_variant = v
        ctx.container_id = f"{ctx.project}-{v}-1"
        return

    if ctx.variant:
        ctx.target_variant = ctx.variant
        cname = f"{ctx.project}-{ctx.variant}-1"
        if _container_exists(cname):
            ctx.container_id = cname
            return
        ctx.reporter.error(
            f"Container not found: {cname}. Please ensure the environment is "
            "running or specify the correct --variant."
        )
        ctx.cancelled = True
        return

    from sanity_gravity.verbs.lifecycle import find_project_containers

    found: list[str] = [
        r["service"]
        for r in find_project_containers(ctx.project, include_stopped=True)
    ]

    if not found:
        ctx.reporter.error(f"No containers found for project '{ctx.project}'.")
        ctx.reporter.info(
            "Tip: This project may not be running yet. "
            "Please run './sanity-cli up' first."
        )
        ctx.cancelled = True
        return
    if len(found) == 1:
        ctx.target_variant = found[0]
        ctx.container_id = f"{ctx.project}-{ctx.target_variant}-1"
        return

    ctx.reporter.info(f"Multiple running environments detected: {', '.join(found)}")
    if not sys.stdin.isatty():
        ctx.reporter.error(
            "Non-interactive mode: please use --variant to "
            "explicitly specify the environment to snapshot."
        )
        ctx.cancelled = True
        return

    print(f"{Colors.BOLD}Select the environment to snapshot:{Colors.ENDC}")
    for i, v in enumerate(found):
        print(f"  [{i + 1}] {v}")
    while True:
        choice = input(
            f"{Colors.OKBLUE}Enter a number "
            f"(1-{len(found)}): {Colors.ENDC}"
        ).strip()
        if choice.isdigit() and 1 <= int(choice) <= len(found):
            ctx.target_variant = found[int(choice) - 1]
            ctx.container_id = f"{ctx.project}-{ctx.target_variant}-1"
            return
        ctx.reporter.warning("Invalid input, please try again.")


def snapshot_commit(ctx) -> None:
    """SNAPSHOT_DOCKER/100: enqueue ``docker commit <container> <tag>``."""
    if ctx.cancelled or ctx.container_id is None:
        return
    ctx.reporter.header(f"Snapshotting {ctx.container_id} -> {ctx.target_tag}")
    ctx.actions.append(RunSubprocess(
        argv=("docker", "commit", ctx.container_id, ctx.target_tag),
    ))


def snapshot_announce(ctx) -> None:
    """SNAPSHOT_DONE/100: success line + usage hint."""
    if ctx.cancelled:
        return
    if ctx.dry_run:
        return  # WouldExecute output speaks for itself.
    ctx.reporter.success(f"Snapshot created: {ctx.target_tag}")
    print(f"\n{Colors.OKBLUE}To use this snapshot:{Colors.ENDC}")
    variant = ctx.target_variant or "<variant>"
    print(f"  ./sanity-cli up -v {variant} --name new-env --image {ctx.target_tag}")


def register_builtin_snapshot_hooks(bus: EventBus) -> None:
    from sanity_gravity.plugins.registry import default_registry
    default_registry()  # ensure plugin hooks.py modules are loaded

    bus.subscribe(Phase.SNAPSHOT_PLAN, snapshot_resolve_project, priority=50)
    bus.subscribe(Phase.SNAPSHOT_PLAN, snapshot_resolve_container, priority=100)
    bus.subscribe(Phase.SNAPSHOT_DOCKER, snapshot_commit, priority=100)
    bus.subscribe(Phase.SNAPSHOT_DONE, snapshot_announce, priority=100)

    get_default_bus().merge_into(bus)
