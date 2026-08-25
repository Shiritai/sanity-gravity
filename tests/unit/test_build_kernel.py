"""The build kernel: phases, plan construction, action enqueueing, dry-run.

Every test runs the real BUILD phase loop with the builtin hooks; the
executor is stubbed so no ``docker build`` ever fires. ``_run_build``
owns the ceremony (bus, hooks, context, orchestrator, optional docker
probe fake); each test states only its request and its assertion.
"""
from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import pytest

from sanity_gravity.core.eventbus import EventBus
from sanity_gravity.core.orchestrator import (
    _BUILD_PHASES,
    BuildContext,
    Orchestrator,
)
from sanity_gravity.core.reporter import Reporter
from sanity_gravity.domain.layers import LayerError, LayerKind, LayerRef
from sanity_gravity.domain.phase import Phase
from sanity_gravity.domain.plan import roots_for
from sanity_gravity.domain.tags import Tag
from sanity_gravity.effects.actions import RunSubprocess
from sanity_gravity.hooks.build import register_builtin_build_hooks


class _Capture:
    """Executor stand-in that records enqueued actions verbatim."""

    def __init__(self) -> None:
        self.actions: list = []

    def drain(self, actions, phase=None) -> None:
        self.actions.extend(actions)


def _run_build(targets=(), *, executor=None, image_exists=None, **ctx_kw):
    """BUILD phases end to end. ``image_exists`` fakes the docker probe
    (None leaves it untouched; dry-run default keeps docker out anyway)."""
    bus = EventBus()
    register_builtin_build_hooks(bus)
    ctx_kw.setdefault("dry_run", True)
    ctx = BuildContext(
        targets=list(targets), reporter=Reporter(sinks=[], run_id="test"),
        **ctx_kw,
    )
    probe = (
        patch("sanity_gravity.hooks.build._image_exists", side_effect=image_exists)
        if image_exists is not None else nullcontext()
    )
    with probe:
        Orchestrator(bus, ctx.reporter, executor=executor).run(_BUILD_PHASES, ctx)
    return ctx


def _layers(ctx) -> list[LayerRef]:
    return [node.layer for node in ctx.plan]


def test_build_phase_sequence_runs_in_order():
    bus = EventBus()
    fired: list[Phase] = []
    for ph in _BUILD_PHASES:
        bus.subscribe(ph, lambda ctx, p=ph: fired.append(p))
    ctx = BuildContext(targets=["cc-none-ssh"], reporter=Reporter(sinks=[], run_id="t"))
    Orchestrator(bus, ctx.reporter).run(_BUILD_PHASES, ctx)
    assert fired == list(_BUILD_PHASES)


def test_build_plan_populates_chain_for_single_target():
    # The full chain: base -> desktop -> agent -> final. Identity, not
    # rendered strings: command shapes are pinned by the golden master.
    assert _layers(_run_build(["cc-none-ssh"])) == [
        LayerRef.base(),
        LayerRef.of_desktop("none"),
        LayerRef.of_agent("cc", "none"),
        LayerRef.of_tag(Tag.parse("cc-none-ssh")),
    ]


def test_build_layer_enqueues_one_docker_build_per_plan_step():
    ex = _Capture()
    _run_build(["cc-none-ssh"], executor=ex)
    assert len(ex.actions) == 4
    for a in ex.actions:
        assert isinstance(a, RunSubprocess)
        assert a.argv[:2] == ("docker", "build")
    assert "sanity-gravity:cc-none-ssh" in ex.actions[-1].argv


def test_no_cache_bypasses_a_hot_probe():
    """--no-cache means the plan ignores every locally present image.
    The surviving mechanism is probe selection at the hook edge
    (build_plan injects NEVER_CACHED when ctx.no_cache) - this pins the
    one line where the flag becomes behavior: with every image present,
    no_cache=True still plans the full chain while the default path
    skips everything but the always-built final."""
    hot = dict(dry_run=False, image_exists=lambda image: True)

    hot_default = _layers(_run_build(["cc-none-ssh"], **hot))
    assert hot_default == [LayerRef.of_tag(Tag.parse("cc-none-ssh"))]

    hot_no_cache = _layers(_run_build(["cc-none-ssh"], no_cache=True, **hot))
    assert len(hot_no_cache) == 4, (
        f"--no-cache must ignore a hot cache; planned only {hot_no_cache}"
    )
    assert hot_no_cache[0] == LayerRef.base()


def test_no_cache_passes_the_docker_flag():
    ex = _Capture()
    _run_build(["cc-none-ssh"], executor=ex, no_cache=True)
    for a in ex.actions:
        assert "--no-cache" in a.argv


def test_build_two_targets_share_their_ancestor_chain():
    """``build A B`` plans the closure ONCE: two finals sharing
    agent+desktop yield 5 nodes (base, desktop, agent, 2 finals), not
    the 8 a per-target expansion would produce - the multi-tag dedup
    contract; no other test would notice its regression."""
    layers = _layers(_run_build(["ag-xfce-kasm", "ag-xfce-vnc"]))
    assert len(layers) == 5, f"expected 5 deduped builds, got {len(layers)}"
    assert layers.count(LayerRef.base()) == 1
    # Depth-major order: the shared chain precedes both finals.
    assert layers[:3] == [
        LayerRef.base(),
        LayerRef.of_desktop("xfce"),
        LayerRef.of_agent("ag", "xfce"),
    ]
    assert set(layers[3:]) == {
        LayerRef.of_tag(Tag.parse("ag-xfce-kasm")),
        LayerRef.of_tag(Tag.parse("ag-xfce-vnc")),
    }


def test_layer_target_base_plans_exactly_the_base_layer():
    """--layer base plans the closure of the base layer: itself, nothing
    else. Deliberately an equality on identities - the previous version
    also pinned plan-entry tuple shapes, which made every structural
    refactor look like a behavior regression."""
    ctx = _run_build([], layer_target="base")
    assert _layers(ctx) == [LayerRef.base()]
    assert ctx.plan[0].parent is None


def test_layer_target_desktop_with_specific():
    layers = _layers(
        _run_build([], layer_target="desktop", layer_target_specific="xfce")
    )
    # Plan must include base + the requested desktop intermediate.
    assert LayerRef.base() in layers
    assert LayerRef.of_desktop("xfce") in layers


def test_layer_connector_with_target_is_rejected():
    """The connector kind used to silently DROP the target and plan the
    whole official connector closure; it must reject instead, pointing
    at the plain-tag form that expresses the same request."""
    with pytest.raises(LayerError, match="plain tag"):
        roots_for(
            tags=(), layer_kind=LayerKind.CONNECTOR,
            layer_target="kasm", official_tags=(),
        )


def test_dry_run_in_executor_does_not_execute():
    """When the Executor is dry-run, the action's runtime is never called."""
    from sanity_gravity.effects.executor import Executor

    fake_runtime = MagicMock()
    reporter = Reporter(sinks=[], run_id="test")
    executor = Executor(runtime=fake_runtime, reporter=reporter, dry_run=True)
    _run_build(["cc-none-ssh"], executor=executor)
    assert fake_runtime.run_subprocess.call_count == 0
    # But the executor recorded would-execute history for each action.
    assert len(executor.history) == 4


def test_build_context_has_no_base_override():
    """The base OS is expressed by the tag dimension and nothing else.

    base_image_override shipped as a dead field (no setter anywhere)
    whose consumer branches would stamp an arbitrary docker ref onto a
    canonical tag name. The concept is eliminated; this guard keeps any
    flag or field from quietly reintroducing a second channel."""
    import dataclasses

    from sanity_gravity.cli.parser import build_parser

    assert "base_image_override" not in {
        f.name for f in dataclasses.fields(BuildContext)
    }
    with pytest.raises(SystemExit):
        build_parser().parse_args(["build", "--base-image", "debian", "cc-none-ssh"])
