"""``snapshot`` verb: ``docker commit`` a running container to a new image tag.

The phase loop ``snapshot.plan → snapshot.docker → snapshot.done`` is
published by :class:`Orchestrator`; per-phase behaviour lives in
:mod:`snapshot_hooks`.
"""
from __future__ import annotations

from sanity_gravity.core.eventbus import EventBus
from sanity_gravity.core.orchestrator import (
    _SNAPSHOT_PHASES,
    Orchestrator,
    SnapshotContext,
)
from sanity_gravity.core.reporter import get_active_reporter as get_reporter
from sanity_gravity.effects.executor import build_default_executor
from sanity_gravity.hooks.snapshot import register_builtin_snapshot_hooks


def snapshot_cmd(args):
    """Snapshot a running container to a new image (kernel-driven)."""
    reporter = getattr(args, "reporter", None) or get_reporter()
    ctx = SnapshotContext(
        project=args.name,
        target_tag=args.tag,
        variant=args.variant,
        reporter=reporter,
        dry_run=bool(getattr(args, "dry_run", False)),
    )

    bus = EventBus()
    register_builtin_snapshot_hooks(bus)
    executor = build_default_executor(reporter, dry_run=ctx.dry_run)

    # ActionFailedError is a SanityError: it flies to the boundary,
    # which exits with e.exit_code (== the action result's code).
    with Orchestrator(bus, reporter, executor=executor) as orch:
        orch.run(_SNAPSHOT_PHASES, ctx)
