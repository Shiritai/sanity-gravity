"""Tests for the snapshot verb's microkernel migration (PR #7b)."""
from __future__ import annotations

from unittest.mock import patch

import pytest


from sanity_gravity.core.eventbus import EventBus
from sanity_gravity.core.orchestrator import (
    Orchestrator,
    SnapshotContext,
    _SNAPSHOT_PHASES,
)
from sanity_gravity.core.reporter import Reporter
from sanity_gravity.domain.phase import Phase
from sanity_gravity.effects.actions import RunSubprocess
from sanity_gravity.hooks.snapshot import (
    register_builtin_snapshot_hooks,
)


def _reporter():
    return Reporter(sinks=[], run_id="test")


def test_snapshot_phase_sequence_runs_in_order():
    bus = EventBus()
    fired: list[Phase] = []
    for ph in _SNAPSHOT_PHASES:
        bus.subscribe(ph, lambda ctx, p=ph: fired.append(p))
    ctx = SnapshotContext(
        project="proj", target_tag="tag:v1", variant="ag-xfce-ssh",
        reporter=_reporter(), dry_run=True,
    )
    Orchestrator(bus, ctx.reporter).run(_SNAPSHOT_PHASES, ctx)
    assert fired == list(_SNAPSHOT_PHASES)


def test_snapshot_resolves_explicit_variant():
    bus = EventBus()
    register_builtin_snapshot_hooks(bus)
    with patch(
        "sanity_gravity.hooks.snapshot.run_command",
        return_value='[{"Id":"x"}]',
    ):
        ctx = SnapshotContext(
            project="proj", target_tag="tag:v1", variant="ag-xfce-ssh",
            reporter=_reporter(), dry_run=False,
        )
        captured: list = []

        class _Exec:
            def drain(self, actions, phase=None):
                captured.extend(actions)

        Orchestrator(bus, ctx.reporter, executor=_Exec()).run(
            _SNAPSHOT_PHASES, ctx,
        )
    assert ctx.container_id == "proj-ag-xfce-ssh-1"
    assert len(captured) == 1
    a = captured[0]
    assert isinstance(a, RunSubprocess)
    assert a.argv == ("docker", "commit", "proj-ag-xfce-ssh-1", "tag:v1")


def test_snapshot_bails_when_explicit_variant_missing():
    bus = EventBus()
    register_builtin_snapshot_hooks(bus)
    # Empty docker inspect output → container "not found".
    with patch(
        "sanity_gravity.hooks.snapshot.run_command",
        return_value="[]",
    ):
        ctx = SnapshotContext(
            project="proj", target_tag="tag:v1", variant="ag-xfce-ssh",
            reporter=_reporter(), dry_run=False,
        )
        captured: list = []

        class _Exec:
            def drain(self, actions, phase=None):
                captured.extend(actions)

        Orchestrator(bus, ctx.reporter, executor=_Exec()).run(
            _SNAPSHOT_PHASES, ctx,
        )
    assert ctx.cancelled is True
    assert captured == []


def test_snapshot_dry_run_uses_placeholder_container():
    """In dry-run we must not invoke docker inspect; container_id is fabricated."""
    bus = EventBus()
    register_builtin_snapshot_hooks(bus)
    ctx = SnapshotContext(
        project="proj", target_tag="tag:v1", variant="ag-xfce-ssh",
        reporter=_reporter(), dry_run=True,
    )
    with patch("sanity_gravity.hooks.snapshot.run_command") as mk:
        Orchestrator(bus, ctx.reporter).run(_SNAPSHOT_PHASES, ctx)
    assert mk.call_count == 0
    assert ctx.container_id == "proj-ag-xfce-ssh-1"
