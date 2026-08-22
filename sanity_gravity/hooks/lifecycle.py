"""Builtin hooks for lifecycle verbs (``down``, ``stop``, ``start``,
``restart``, ``clean``).

Phase split:
- ``LIFECYCLE_BEFORE`` — for ``down``: verify the project exists; for ``clean``:
  prompt for confirmation. Always: recover env from a running container.
- ``LIFECYCLE_DOCKER`` — enqueue the ``docker compose <action>`` Action.
- ``LIFECYCLE_AFTER`` — emit the success message keyed off the action verb.

These verbs resolve containers purely via the ``-p <project>`` label and
need no compose file. An earlier design scanned ``config/`` for per-tag
composes and passed them with ``-f``; that was wrong twice over — the
per-tag service names (``ag-xfce-kasm``) don't match a legacy project's
running service (``kasm``) so ``restart`` silently no-op'd, and the
empty-scan fallback pointed at a ``docker-compose.yml`` that no longer
exists. See upstream commit 9457bfd.
"""
from __future__ import annotations

import sys

from sanity_gravity.core.colors import Colors
from sanity_gravity.core.command import CommandBuilder
from sanity_gravity.core.eventbus import EventBus, get_default_bus
from sanity_gravity.domain.phase import Phase
from sanity_gravity.effects.actions import RunSubprocess


def lifecycle_check_existence(ctx) -> None:
    """LIFECYCLE_BEFORE/100: ``down`` only — bail if project missing.

    The hook is declared ``skip_in_dry_run=True`` at subscription so
    the orchestrator drops it entirely in dry-run; ``get_active_projects``
    shells out to ``docker ps`` and that exactly the kind of read with
    side effects (audit log, hang if daemon is down) that dry-run is
    meant to avoid.
    """
    if not ctx.check_existence:
        return

    # Local import to avoid module-level cycle (lifecycle.py imports this).
    from sanity_gravity.verbs.lifecycle import get_active_projects

    active = get_active_projects()
    if ctx.project not in active:
        ctx.reporter.warning(f"Project '{ctx.project}' not found.")
        if active:
            ctx.reporter.info(f"Active projects: {', '.join(active)}")
            ctx.reporter.info(
                "Tip: Use --name <project> to specify a project."
            )
        else:
            ctx.reporter.info("No active Sanity-Gravity projects found.")
        ctx.project_exists = False


def lifecycle_clean_prompt(ctx) -> None:
    """LIFECYCLE_BEFORE/50: ``clean`` only — interactive confirmation."""
    # CleanContext has a `force` attribute; plain DownContext does not.
    if not hasattr(ctx, "force"):
        return
    if ctx.force:
        return
    print(
        f"{Colors.WARNING}CAUTION: This will destroy ALL data in volumes "
        f"for project '{ctx.project}'.{Colors.ENDC}"
    )
    if sys.stdin.isatty():
        choice = input(
            f"{Colors.BOLD}Proceed with deep clean? [y/N]: {Colors.ENDC}"
        ).lower().strip()
        if choice != "y":
            ctx.reporter.info("Cleanup cancelled.")
            ctx.cancelled = True


def lifecycle_recover_env(ctx) -> None:
    """LIFECYCLE_BEFORE/300: recover environment from a running container.

    Declared ``skip_in_dry_run=True`` at subscription — the docker
    inspect is pure side effect with nothing to preview.
    """
    if getattr(ctx, "project_exists", True) is False:
        return
    if getattr(ctx, "cancelled", False):
        return

    from sanity_gravity.verbs.lifecycle import get_project_env

    ctx.env = get_project_env(ctx.project) or {}


def _emit_header(ctx) -> None:
    label = ctx.action.capitalize()
    if ctx.action == "down" and ctx.extra_action_args:
        label = "Deep Cleaning"
    ctx.reporter.header(f"{label}{'ing' if not label.endswith('ing') else ''} Sandbox ({ctx.project})")


def lifecycle_compose_action(ctx) -> None:
    """LIFECYCLE_DOCKER/100: enqueue ``docker compose -p <name> <action>``."""
    if getattr(ctx, "project_exists", True) is False:
        return
    if getattr(ctx, "cancelled", False):
        return

    # Header line: print before enqueueing, so it precedes the action's
    # 'would-execute' / 'started' line in the output.
    label_word = "Cleaning" if ctx.extra_action_args else (
        "Stopping" if ctx.action == "stop" else
        "Starting" if ctx.action == "start" else
        "Restarting" if ctx.action == "restart" else
        "Removing"
    )
    if ctx.extra_action_args:
        ctx.reporter.header(f"Deep Cleaning Sandbox ({ctx.project})")
    else:
        ctx.reporter.header(f"{label_word} Sandbox ({ctx.project})")

    # No -f: the project label is the only correct container selector
    # for restart/stop/start/down/clean. (Compose files are needed only
    # by `up` / `upgrade`, which create containers.)
    cb = CommandBuilder("docker", "compose", "-p", ctx.project)
    cb.positional(ctx.action, *ctx.extra_action_args)
    ctx.actions.append(RunSubprocess(argv=cb.build(), env=dict(ctx.env) or None))


def lifecycle_announce(ctx) -> None:
    """LIFECYCLE_AFTER/100: success message keyed on action verb."""
    if getattr(ctx, "project_exists", True) is False:
        return
    if getattr(ctx, "cancelled", False):
        return
    if ctx.dry_run:
        # Skip success claim in dry-run; the WouldExecute lines speak for themselves.
        return
    if ctx.extra_action_args:
        ctx.reporter.success("Deep cleanup complete.")
        return
    msgs = {
        "down": "All containers removed.",
        "stop": "Containers stopped (data preserved).",
        "start": "Containers started.",
        "restart": "Containers restarted.",
    }
    msg = msgs.get(ctx.action)
    if msg:
        ctx.reporter.success(msg)


def register_builtin_lifecycle_hooks(bus: EventBus) -> None:
    """Subscribe lifecycle hooks. Same hooks serve down/stop/start/restart/clean.

    The ``clean`` prompt is also registered here at priority 50 (before
    the existence check) — it short-circuits via ``ctx.cancelled``.
    """
    from sanity_gravity.plugins.registry import default_registry
    default_registry()  # ensure plugin hooks.py modules are loaded

    bus.subscribe(Phase.LIFECYCLE_BEFORE, lifecycle_clean_prompt, priority=50)
    bus.subscribe(Phase.LIFECYCLE_BEFORE, lifecycle_check_existence,
                  priority=100, skip_in_dry_run=True)
    bus.subscribe(Phase.LIFECYCLE_BEFORE, lifecycle_recover_env,
                  priority=300, skip_in_dry_run=True)
    bus.subscribe(Phase.LIFECYCLE_DOCKER, lifecycle_compose_action, priority=100)
    bus.subscribe(Phase.LIFECYCLE_AFTER, lifecycle_announce, priority=100)

    get_default_bus().merge_into(bus)
