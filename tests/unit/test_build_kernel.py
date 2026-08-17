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
from sanity_gravity.domain.layers import LayerError, LayerKind, LayerRef
from sanity_gravity.domain.plan import roots_for
from sanity_gravity.domain.tags import Tag
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
    # The full chain: base -> desktop -> agent -> final. Identity, not
    # rendered strings: command shapes are pinned by the golden master.
    assert [node.layer for node in ctx.plan] == [
        LayerRef.base(),
        LayerRef.of_desktop("none"),
        LayerRef.of_agent("cc", "none"),
        LayerRef.of_tag(Tag.parse("cc-none-ssh")),
    ]


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


def test_build_layer_target_base_plans_exactly_the_base_layer():
    """--layer base plans the closure of the base layer: itself, nothing
    else. Deliberately an equality on identities - the previous version
    also pinned "a plan entry is an indexable tuple whose slot 1 is a
    rendered name", which made every structural refactor look like a
    behavior regression."""
    bus = EventBus()
    register_builtin_build_hooks(bus)
    ctx = _ctx([], layer_target="base")
    Orchestrator(bus, ctx.reporter).run(_BUILD_PHASES, ctx)
    assert [node.layer for node in ctx.plan] == [LayerRef.base()]
    assert ctx.plan[0].parent is None


def test_build_layer_target_desktop_with_specific():
    bus = EventBus()
    register_builtin_build_hooks(bus)
    ctx = _ctx([], layer_target="desktop", layer_target_specific="xfce")
    Orchestrator(bus, ctx.reporter).run(_BUILD_PHASES, ctx)
    layers = [node.layer for node in ctx.plan]
    # Plan must include base + the requested desktop intermediate.
    assert LayerRef.base() in layers
    assert LayerRef.of_desktop("xfce") in layers


def test_build_layer_connector_with_target_is_rejected():
    """Same flag, same treatment: --layer base/desktop/agent with a
    --layer-target selects that one layer, and BASE + target already
    raises. The connector kind used to silently DROP the target and
    plan the whole official connector closure; it must reject instead,
    pointing at the plain-tag form that expresses the same request."""
    with pytest.raises(LayerError, match="plain tag"):
        roots_for(
            tags=(),
            layer_kind=LayerKind.CONNECTOR,
            layer_target="kasm",
            official_tags=(),
        )


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


def test_build_context_has_no_base_override():
    """The base OS is expressed by the tag dimension and nothing else.

    base_image_override shipped as a dead field (no setter anywhere) whose
    two consumer branches would stamp an arbitrary docker ref onto a
    canonical tag name. The concept is eliminated; this guard keeps any
    flag or field from quietly reintroducing a second channel."""
    import dataclasses

    from sanity_gravity.cli.parser import build_parser
    from sanity_gravity.core.orchestrator import BuildContext

    assert "base_image_override" not in {
        f.name for f in dataclasses.fields(BuildContext)
    }

    with pytest.raises(SystemExit):
        build_parser().parse_args(["build", "--base-image", "debian", "cc-none-ssh"])
