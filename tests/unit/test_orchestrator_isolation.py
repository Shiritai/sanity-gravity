"""End-to-end tests for the orchestrator's plugin-hook isolation.

The orchestrator catches exceptions from ``isolated`` hooks, emits a
warning via the reporter, drops any actions the hook had appended
before raising, and continues to the next hook. Builtins (non-isolated)
still propagate.
"""
from __future__ import annotations

import pytest

from sanity_gravity.core.eventbus import EventBus
from sanity_gravity.core.orchestrator import Orchestrator
from sanity_gravity.domain.phase import Phase
from sanity_gravity.effects.actions import RunSubprocess


class _RecorderReporter:
    """Minimal Reporter stand-in capturing attribute calls by category."""

    def __init__(self):
        self.run_id = "iso-test"
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name):
        def _fn(*a, **kw):
            self.calls.append((name, a, kw))
        return _fn


class _Ctx:
    """Tiny context with an actions queue + drain_actions, like UpContext."""

    def __init__(self):
        self.actions: list = []

    def drain_actions(self):
        out = list(self.actions)
        self.actions.clear()
        return out


class _RecorderExecutor:
    def __init__(self):
        self.batches: list[list] = []

    def drain(self, actions, *, phase=None):
        self.batches.append(list(actions))


class TestOrchestratorIsolatedHookRuntime:

    def test_isolated_hook_exception_emits_warning_and_continues(self):
        bus = EventBus()
        fired = []

        def boom(ctx):
            raise ValueError("plugin exploded")

        def good(ctx):
            fired.append("good")

        bus.subscribe(Phase.UP_ANNOUNCE, boom, isolated=True, name="boom")
        bus.subscribe(Phase.UP_ANNOUNCE, good, isolated=True, name="good")

        rep = _RecorderReporter()
        ctx = _Ctx()
        Orchestrator(bus, rep).run([Phase.UP_ANNOUNCE], ctx)

        # ``good`` ran despite ``boom``.
        assert fired == ["good"]
        # A warning was emitted naming the hook + phase + exception.
        warnings = [c for c in rep.calls if c[0] == "warning"]
        assert len(warnings) == 1
        msg = warnings[0][1][0]
        assert "boom" in msg
        assert "up.announce" in msg
        assert "ValueError" in msg
        assert "plugin exploded" in msg

    def test_isolated_hook_partial_actions_discarded(self):
        """A plugin hook that appends actions and then raises must not
        leave those actions in the queue — running them would defeat
        isolation."""
        bus = EventBus()

        def half_then_raise(ctx):
            ctx.actions.append(RunSubprocess(argv=("evil",)))
            ctx.actions.append(RunSubprocess(argv=("more",)))
            raise RuntimeError("died after appending")

        bus.subscribe(Phase.UP_DOCKER, half_then_raise, isolated=True)

        rep = _RecorderReporter()
        ctx = _Ctx()
        ex = _RecorderExecutor()
        Orchestrator(bus, rep, executor=ex).run([Phase.UP_DOCKER], ctx)

        # No actions should have been drained — the hook's appends were
        # rolled back when it raised.
        assert ex.batches == []

    def test_isolated_hook_actions_before_failure_in_same_phase_preserved(self):
        """Actions queued by a *previous* (succeeded) isolated hook in
        the same phase must still execute. Only the *failing* hook's
        appends are rolled back."""
        bus = EventBus()

        def good_first(ctx):
            ctx.actions.append(RunSubprocess(argv=("good",)))

        def bad_second(ctx):
            ctx.actions.append(RunSubprocess(argv=("bad",)))
            raise RuntimeError("bye")

        bus.subscribe(Phase.UP_DOCKER, good_first, isolated=True, priority=100)
        bus.subscribe(Phase.UP_DOCKER, bad_second, isolated=True, priority=200)

        rep = _RecorderReporter()
        ctx = _Ctx()
        ex = _RecorderExecutor()
        Orchestrator(bus, rep, executor=ex).run([Phase.UP_DOCKER], ctx)

        # First hook's action drained between hooks; second hook's
        # action discarded.
        all_actions = [a for batch in ex.batches for a in batch]
        argvs = [a.argv for a in all_actions]
        assert ("good",) in argvs
        assert ("bad",) not in argvs

    def test_non_isolated_hook_propagates(self):
        """A builtin (non-isolated) hook's exception must still abort
        the run."""
        bus = EventBus()

        def boom(ctx):
            raise RuntimeError("builtin invariant")

        bus.subscribe(Phase.UP_VALIDATE, boom, isolated=False)
        rep = _RecorderReporter()
        ctx = _Ctx()
        with pytest.raises(RuntimeError, match="builtin invariant"):
            Orchestrator(bus, rep).run([Phase.UP_VALIDATE], ctx)

    def test_isolated_hook_systemexit_propagates(self):
        """SystemExit from an isolated hook must NOT be swallowed."""
        bus = EventBus()

        def hook_exits(ctx):
            raise SystemExit(2)

        bus.subscribe(Phase.UP_VALIDATE, hook_exits, isolated=True)
        rep = _RecorderReporter()
        ctx = _Ctx()
        with pytest.raises(SystemExit):
            Orchestrator(bus, rep).run([Phase.UP_VALIDATE], ctx)

    def test_isolated_hook_keyboardinterrupt_propagates(self):
        bus = EventBus()

        def hook_kbd(ctx):
            raise KeyboardInterrupt()

        bus.subscribe(Phase.UP_VALIDATE, hook_kbd, isolated=True)
        rep = _RecorderReporter()
        ctx = _Ctx()
        with pytest.raises(KeyboardInterrupt):
            Orchestrator(bus, rep).run([Phase.UP_VALIDATE], ctx)

    def test_isolated_hook_oserror_caught(self):
        """Plain Exception subclasses (including OSError) are caught.

        Note: ``OSError(13, ...)`` is auto-promoted to
        ``PermissionError`` by CPython; we assert on the EACCES message
        instead so the test is stable across Python versions.
        """
        bus = EventBus()

        def hook_os(ctx):
            raise OSError(13, "EACCES denied")

        bus.subscribe(Phase.UP_VALIDATE, hook_os, isolated=True)
        rep = _RecorderReporter()
        ctx = _Ctx()
        # Must not raise — orchestrator absorbs the error.
        Orchestrator(bus, rep).run([Phase.UP_VALIDATE], ctx)
        warnings = [c for c in rep.calls if c[0] == "warning"]
        assert any("EACCES denied" in c[1][0] for c in warnings)
