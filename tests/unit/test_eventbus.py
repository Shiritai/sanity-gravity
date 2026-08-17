"""Tests for the EventBus + Phase pair introduced in PR #4.

The bus is the smallest piece of the microkernel; we cover:

- subscribe / publish round-trip,
- priority ordering with ties broken by registration order,
- multiple hooks per phase,
- the ``@on`` decorator landing on the module-level default bus,
- ``hooks_for`` returning a stable, sorted view useful for debugging.
"""
from __future__ import annotations

from sanity_gravity.core.eventbus import EventBus, Hook, get_default_bus, on
from sanity_gravity.domain.phase import Phase
from sanity_gravity.domain.tags import Tag


def test_subscribe_and_publish_invokes_hook():
    bus = EventBus()
    seen = []
    bus.subscribe(Phase.UP_VALIDATE, lambda ctx: seen.append(("a", ctx)))
    bus.publish(Phase.UP_VALIDATE, "ctx")
    assert seen == [("a", "ctx")]


def test_publish_no_subscribers_is_noop():
    EventBus().publish(Phase.UP_DOCKER, object())  # must not raise


def test_priority_orders_lower_first():
    bus = EventBus()
    order = []
    bus.subscribe(Phase.UP_COMPOSE, lambda c: order.append("late"), priority=300)
    bus.subscribe(Phase.UP_COMPOSE, lambda c: order.append("early"), priority=100)
    bus.subscribe(Phase.UP_COMPOSE, lambda c: order.append("mid"), priority=200)
    bus.publish(Phase.UP_COMPOSE, None)
    assert order == ["early", "mid", "late"]


def test_equal_priority_preserves_registration_order():
    bus = EventBus()
    order = []
    for label in ("first", "second", "third"):
        bus.subscribe(Phase.UP_DOCKER, lambda c, l=label: order.append(l))
    bus.publish(Phase.UP_DOCKER, None)
    assert order == ["first", "second", "third"]


def test_multiple_hooks_per_phase_all_fire():
    bus = EventBus()
    counters = {"a": 0, "b": 0}
    bus.subscribe(Phase.UP_PROVISION, lambda c: counters.__setitem__("a", counters["a"] + 1))
    bus.subscribe(Phase.UP_PROVISION, lambda c: counters.__setitem__("b", counters["b"] + 1))
    bus.publish(Phase.UP_PROVISION, None)
    bus.publish(Phase.UP_PROVISION, None)
    assert counters == {"a": 2, "b": 2}


def test_hook_exception_propagates():
    bus = EventBus()

    def boom(ctx):
        raise RuntimeError("nope")

    bus.subscribe(Phase.UP_VALIDATE, boom)
    try:
        bus.publish(Phase.UP_VALIDATE, None)
    except RuntimeError as e:
        assert str(e) == "nope"
    else:  # pragma: no cover - guard
        raise AssertionError("expected RuntimeError to propagate")


def test_named_hook_recorded_for_introspection():
    bus = EventBus()

    def my_hook(ctx):
        pass

    h = bus.subscribe(Phase.UP_DOCKER, my_hook, name="custom-name")
    assert h.name == "custom-name"
    listed = bus.hooks_for(Phase.UP_DOCKER)
    assert listed == [h]
    # default name = fn.__name__
    h2 = bus.subscribe(Phase.UP_DOCKER, my_hook)
    assert h2.name == "my_hook"


def test_hooks_for_returns_sorted_copy():
    bus = EventBus()
    a = bus.subscribe(Phase.UP_ANNOUNCE, lambda c: None, priority=200)
    b = bus.subscribe(Phase.UP_ANNOUNCE, lambda c: None, priority=100)
    listed = bus.hooks_for(Phase.UP_ANNOUNCE)
    assert listed == [b, a]
    # mutating the returned list should not affect the bus's view
    listed.clear()
    assert bus.hooks_for(Phase.UP_ANNOUNCE) == [b, a]


def test_on_decorator_registers_on_default_bus():
    default = get_default_bus()
    before = len(default.hooks_for(Phase.UP_VALIDATE))

    @on(Phase.UP_VALIDATE, priority=42)
    def _decorated(ctx):
        pass

    after = default.hooks_for(Phase.UP_VALIDATE)
    assert len(after) == before + 1
    assert after[-1].priority == 42 or any(h.priority == 42 for h in after)


def test_phase_str_value_round_trip():
    # Phase is a StrEnum: its value is the string form.
    assert Phase.UP_DOCKER.value == "up.docker"
    assert str(Phase.UP_DOCKER) == "up.docker"


def test_subscribe_with_isolated_flag_marks_hook():
    """A hook subscribed with ``isolated=True`` must carry that flag —
    the orchestrator relies on it to decide whether to wrap dispatch in
    a try/except."""
    bus = EventBus()
    h = bus.subscribe(Phase.UP_DOCKER, lambda c: None, isolated=True)
    assert h.isolated is True
    not_iso = bus.subscribe(Phase.UP_DOCKER, lambda c: None)
    assert not_iso.isolated is False


def test_publish_isolated_hook_exception_caught_with_handler():
    """``publish(on_isolated_error=...)`` catches Exception from
    isolated hooks and continues to subsequent hooks."""
    bus = EventBus()
    seen = []

    def boom(ctx):
        raise ValueError("plugin crash")

    def good(ctx):
        seen.append("good")

    bus.subscribe(Phase.UP_VALIDATE, boom, isolated=True, name="boom")
    bus.subscribe(Phase.UP_VALIDATE, good, isolated=True, name="good")

    captured = []
    bus.publish(
        Phase.UP_VALIDATE, None,
        on_isolated_error=lambda h, e: captured.append((h.name, str(e))),
    )
    assert seen == ["good"]
    assert captured == [("boom", "plugin crash")]


def test_publish_isolated_hook_does_not_swallow_systemexit():
    """SystemExit / KeyboardInterrupt MUST propagate even from an
    isolated hook — those represent user / interpreter intent, not
    plugin misbehaviour."""
    bus = EventBus()

    def hook_exits(ctx):
        raise SystemExit(2)

    bus.subscribe(Phase.UP_VALIDATE, hook_exits, isolated=True)
    import pytest as _pt
    with _pt.raises(SystemExit):
        bus.publish(
            Phase.UP_VALIDATE, None,
            on_isolated_error=lambda h, e: None,  # never called
        )


def test_publish_non_isolated_hook_propagates():
    """A non-isolated (builtin) hook's exception must propagate even
    if ``on_isolated_error`` is set — builtins encode kernel
    invariants that callers must honor."""
    bus = EventBus()

    def boom(ctx):
        raise RuntimeError("builtin invariant")

    bus.subscribe(Phase.UP_VALIDATE, boom, isolated=False)

    import pytest as _pt
    with _pt.raises(RuntimeError, match="builtin invariant"):
        bus.publish(
            Phase.UP_VALIDATE, None,
            on_isolated_error=lambda h, e: None,
        )


def test_publish_without_handler_isolated_hook_propagates():
    """Without ``on_isolated_error``, even an isolated hook's exception
    propagates (legacy behaviour: callers using ``publish`` directly
    don't get the safety net for free)."""
    bus = EventBus()

    def boom(ctx):
        raise ValueError("isolated but no handler")

    bus.subscribe(Phase.UP_VALIDATE, boom, isolated=True)
    import pytest as _pt
    with _pt.raises(ValueError):
        bus.publish(Phase.UP_VALIDATE, None)


def test_merge_into_marks_hooks_isolated_by_default():
    """``merge_into`` defaults to ``isolate=True`` — plugin hooks
    spliced via the default bus inherit the safety net automatically."""
    src = EventBus()
    src.subscribe(Phase.UP_ANNOUNCE, lambda c: None, name="plugin_hook")

    dst = EventBus()
    src.merge_into(dst)

    [hook] = dst.hooks_for(Phase.UP_ANNOUNCE)
    assert hook.isolated is True
    assert hook.name == "plugin_hook"


def test_skip_in_dry_run_flag_stored_on_hook():
    bus = EventBus()
    h = bus.subscribe(Phase.UP_DOCKER, lambda c: None, skip_in_dry_run=True)
    assert h.skip_in_dry_run is True
    h2 = bus.subscribe(Phase.UP_DOCKER, lambda c: None)
    assert h2.skip_in_dry_run is False


def test_publish_skips_skip_in_dry_run_hooks_when_dry_run():
    """When ``ctx.dry_run`` is True, hooks marked ``skip_in_dry_run``
    are not dispatched at all — neither their side effects nor any
    "skipped" messages from inside them."""

    class _Ctx:
        dry_run = True

    bus = EventBus()
    fired = []
    bus.subscribe(
        Phase.UP_DOCKER, lambda c: fired.append("skipped"),
        skip_in_dry_run=True,
    )
    bus.subscribe(Phase.UP_DOCKER, lambda c: fired.append("ran"))
    bus.publish(Phase.UP_DOCKER, _Ctx())
    assert fired == ["ran"]


def test_publish_runs_skip_in_dry_run_hooks_when_not_dry_run():
    class _Ctx:
        dry_run = False

    bus = EventBus()
    fired = []
    bus.subscribe(
        Phase.UP_DOCKER, lambda c: fired.append("ran-skippable"),
        skip_in_dry_run=True,
    )
    bus.publish(Phase.UP_DOCKER, _Ctx())
    assert fired == ["ran-skippable"]


def test_merge_into_isolate_false_preserves_origin_flag():
    """``merge_into(isolate=False)`` preserves the source ``isolated``
    flag instead of overriding to True. Used when splicing hooks that
    are part of the kernel's correctness story."""
    src = EventBus()
    src.subscribe(Phase.UP_ANNOUNCE, lambda c: None, name="builtin_a", isolated=False)
    src.subscribe(Phase.UP_ANNOUNCE, lambda c: None, name="builtin_b", isolated=True)

    dst = EventBus()
    src.merge_into(dst, isolate=False)

    flags = {h.name: h.isolated for h in dst.hooks_for(Phase.UP_ANNOUNCE)}
    assert flags == {"builtin_a": False, "builtin_b": True}


def test_tag_parse_round_trip():
    parsed = Tag.parse("ag-xfce-kasm")
    assert parsed.agent == "ag"
    assert parsed.desktop == "xfce"
    assert parsed.connector == "kasm"
    assert str(parsed) == "ag-xfce-kasm"
