"""Tests for the build verb's microkernel migration (PR #7b).

These tests run the BUILD phase loop against a stubbed Executor so no
real ``docker build`` ever fires. They verify the phase sequence, plan
construction, action enqueueing, and the ``--dry-run`` path.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


from sanity_gravity.core.eventbus import EventBus
from sanity_gravity.core.orchestrator import (
    BuildContext,
    Orchestrator,
    _BUILD_PHASES,
)
from sanity_gravity.core.reporter import Reporter
from sanity_gravity.domain.phase import Phase
from sanity_gravity.effects.actions import RunSubprocess
from sanity_gravity.hooks.build import (
    register_builtin_build_hooks,
)


def _reporter():
    return Reporter(sinks=[], run_id="test")


def _ctx(targets, **kw):
    """BuildContext + dry-run defaults so cache lookups never touch docker."""
    kw.setdefault("dry_run", True)
    return BuildContext(targets=list(targets), reporter=_reporter(), **kw)


def test_build_phase_sequence_runs_in_order():
    bus = EventBus()
    fired: list[Phase] = []
    for ph in _BUILD_PHASES:
        bus.subscribe(ph, lambda ctx, p=ph: fired.append(p))
    ctx = _ctx(["cc-none-ssh"])
    Orchestrator(bus, ctx.reporter).run(_BUILD_PHASES, ctx)
    assert fired == list(_BUILD_PHASES)


def test_build_plan_populates_chain_for_single_target():
    bus = EventBus()
    register_builtin_build_hooks(bus)
    ctx = _ctx(["cc-none-ssh"])
    Orchestrator(bus, ctx.reporter).run(_BUILD_PHASES, ctx)
    image_names = [step[1] for step in ctx.plan]
    # The full chain: base → _base-none → _cc-none → cc-none-ssh
    assert image_names == ["_base", "_base-none", "_cc-none", "cc-none-ssh"]


def test_build_layer_enqueues_one_action_per_plan_step():
    bus = EventBus()
    register_builtin_build_hooks(bus)
    ctx = _ctx(["cc-none-ssh"])

    captured: list = []

    class _Exec:
        def drain(self, actions, phase=None):
            captured.extend(actions)

    Orchestrator(bus, ctx.reporter, executor=_Exec()).run(_BUILD_PHASES, ctx)
    assert all(isinstance(a, RunSubprocess) for a in captured)
    assert len(captured) == 4
    # Each action should be a docker build invocation.
    for a in captured:
        assert a.argv[0] == "docker" and a.argv[1] == "build"
    # Final tag should appear in the last action.
    assert "sanity-gravity:cc-none-ssh" in captured[-1].argv


def test_build_layer_no_cache_passes_flag():
    bus = EventBus()
    register_builtin_build_hooks(bus)
    ctx = _ctx(["cc-none-ssh"], no_cache=True)

    captured: list = []

    class _Exec:
        def drain(self, actions, phase=None):
            captured.extend(actions)

    Orchestrator(bus, ctx.reporter, executor=_Exec()).run(_BUILD_PHASES, ctx)
    for a in captured:
        assert "--no-cache" in a.argv


def test_build_layer_target_base_only_builds_base():
    bus = EventBus()
    register_builtin_build_hooks(bus)
    ctx = _ctx([], layer_target="base")
    Orchestrator(bus, ctx.reporter).run(_BUILD_PHASES, ctx)
    assert [s[1] for s in ctx.plan] == ["_base"]


def test_build_layer_target_desktop_with_specific():
    bus = EventBus()
    register_builtin_build_hooks(bus)
    ctx = _ctx([], layer_target="desktop", layer_target_specific="xfce")
    Orchestrator(bus, ctx.reporter).run(_BUILD_PHASES, ctx)
    names = [s[1] for s in ctx.plan]
    # Plan must include base + the requested desktop intermediate.
    assert "_base" in names
    assert "_base-xfce" in names


def test_build_dry_run_in_executor_does_not_execute():
    """When the Executor is dry-run, the action's runtime is never called."""
    from sanity_gravity.effects.executor import Executor

    fake_runtime = MagicMock()
    bus = EventBus()
    register_builtin_build_hooks(bus)
    ctx = _ctx(["cc-none-ssh"])
    executor = Executor(runtime=fake_runtime, reporter=ctx.reporter, dry_run=True)
    Orchestrator(bus, ctx.reporter, executor=executor).run(_BUILD_PHASES, ctx)
    assert fake_runtime.run_subprocess.call_count == 0
    # But the executor recorded would-execute history for each action.
    assert len(executor.history) == 4
