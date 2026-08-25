"""Typed pub/sub event bus with priority-ordered hooks.

Hooks subscribe to a :class:`Phase`, the orchestrator publishes phases in
order, and each hook receives a shared mutable context. Hooks are called
by ``priority`` (lower first), then registration order.

Two failure modes:

- **Builtin hooks** (subscribed directly by a verb's
  ``register_builtin_*_hooks``) propagate exceptions. The orchestrator
  decides how to surface them — typically by aborting the run, since
  builtins encode invariants the kernel needs (validation, port alloc,
  etc.).
- **Plugin-contributed hooks** (registered against the module-level
  default bus via ``@on`` and merged in via :meth:`EventBus.merge_into`)
  are marked ``isolated=True``. If they raise, the orchestrator reports
  the failure and continues to the next hook. A buggy third-party plugin
  must not be able to abort an ``up`` flow midway.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sanity_gravity.domain.phase import Phase

HookFn = Callable[[Any], None]


# ---------------------------------------------------------------------------
# Priority convention
# ---------------------------------------------------------------------------
#
# Hooks within a phase fire in priority order (lower first). Builtin hooks
# space their priorities at 100 / 200 / 300 so plugin hooks can slot in
# between, before, or after without renumbering. The convention:
#
#   < 100        : run BEFORE the first builtin (sanity-check, gate, abort)
#   == 100       : first builtin slot (the canonical action of the phase)
#   100 < p < 200: between first and second builtin (rare)
#   == 200       : second builtin (post-action observers)
#   == 300       : third builtin (cleanup / announce)
#   > 300        : tail of the phase (audit, telemetry)
#
# Plugin authors should use these as anchor points. The constants are
# exported so plugin hooks.py modules can write
#
#     @on(Phase.UP_ANNOUNCE, priority=PRIORITY_AFTER_FIRST)
#
# instead of hand-rolling integer literals.

PRIORITY_BEFORE_BUILTIN: int = 50
PRIORITY_BUILTIN_FIRST: int = 100
PRIORITY_AFTER_FIRST: int = 150
PRIORITY_BUILTIN_SECOND: int = 200
PRIORITY_BUILTIN_THIRD: int = 300
PRIORITY_TAIL: int = 500


@dataclass(frozen=True)
class Hook:
    """A single subscription. ``name`` is for debugging only.

    Flags:

    - ``isolated``: plugin-contributed hooks; the orchestrator catches
      and reports any exception they raise instead of aborting the
      run. Builtin hooks default to ``False`` and can abort.
    - ``skip_in_dry_run``: pure side-effect hooks that have nothing
      meaningful to preview. The orchestrator skips them entirely when
      ``ctx.dry_run`` is True. Hooks that emit a "would do X" preview
      line should NOT set this — they should check ``ctx.dry_run``
      themselves so the preview is emitted.
    """

    phase: Phase
    fn: HookFn
    priority: int = 100
    name: str | None = None
    isolated: bool = False
    skip_in_dry_run: bool = False
    _seq: int = field(default=0, compare=False)


class EventBus:
    """Phase-keyed registry of hooks with priority dispatch."""

    def __init__(self) -> None:
        self._hooks: dict[Phase, list[Hook]] = {}
        self._counter: int = 0

    def subscribe(self, phase: Phase, fn: HookFn, *,
                  priority: int = 100, name: str | None = None,
                  isolated: bool = False,
                  skip_in_dry_run: bool = False) -> Hook:
        """Register ``fn`` to be called when ``phase`` is published.

        ``isolated=True`` marks the hook as plugin-contributed: the
        orchestrator wraps its dispatch in try/except so the run does not
        abort if it raises. Builtins leave the default (``False``).

        ``skip_in_dry_run=True`` declares the hook as pure side-effect
        with nothing to preview; the orchestrator skips it entirely
        when ``ctx.dry_run`` is True.
        """
        self._counter += 1
        hook = Hook(phase=phase, fn=fn, priority=priority,
                    name=name or getattr(fn, "__name__", "<anon>"),
                    isolated=isolated,
                    skip_in_dry_run=skip_in_dry_run,
                    _seq=self._counter)
        self._hooks.setdefault(phase, []).append(hook)
        return hook

    def publish(self, phase: Phase, ctx: Any, *,
                on_isolated_error: Callable[[Hook, BaseException], None] | None = None) -> None:
        """Dispatch ``ctx`` to every hook bound to ``phase`` in order.

        If ``on_isolated_error`` is provided, exceptions raised by
        ``isolated`` hooks are passed to it and dispatch continues.
        Without a handler, isolated-hook errors propagate (preserves the
        legacy behaviour for callers that use ``publish`` directly).
        Builtin (non-isolated) hooks always propagate.
        """
        dry_run = bool(getattr(ctx, "dry_run", False))
        for hook in self.hooks_for(phase):
            if dry_run and hook.skip_in_dry_run:
                continue
            if hook.isolated and on_isolated_error is not None:
                try:
                    hook.fn(ctx)
                except Exception as exc:  # plugin-contributed; isolate
                    # Catch ``Exception`` (not ``BaseException``) so
                    # ``SystemExit`` / ``KeyboardInterrupt`` still abort
                    # the run — those are user / interpreter intent,
                    # not plugin misbehaviour to swallow.
                    on_isolated_error(hook, exc)
            else:
                hook.fn(ctx)

    def hooks_for(self, phase: Phase) -> list[Hook]:
        """Return hooks for ``phase`` in dispatch order (sorted copy)."""
        hooks = self._hooks.get(phase, [])
        return sorted(hooks, key=lambda h: (h.priority, h._seq))

    def all_hooks(self) -> list[Hook]:
        """Flat list of every subscribed hook, in registration order."""
        out: list[Hook] = []
        for hooks in self._hooks.values():
            out.extend(hooks)
        out.sort(key=lambda h: h._seq)
        return out

    def merge_into(self, other: EventBus, *, isolate: bool = True) -> None:
        """Re-subscribe every hook on ``self`` onto ``other``.

        Used to splice plugin-contributed hooks (registered against the
        module-level default bus via ``@on``) into a per-verb bus before
        the orchestrator runs.

        ``isolate`` controls how merged hooks are dispatched:

        - ``True`` (default, plugin-style): merged hooks are marked
          ``isolated=True`` so a buggy third-party plugin cannot abort
          the verb's phase loop — the orchestrator reports the failure
          and continues with the next hook.
        - ``False`` (builtin-style): the original ``Hook.isolated`` flag
          on each source hook is preserved. Use this when splicing
          hooks that are part of the kernel's correctness story and
          must be allowed to abort.

        Builtin hooks normally subscribe directly to the per-verb bus
        and never go through ``merge_into``.
        """
        for h in self.all_hooks():
            other.subscribe(
                h.phase, h.fn,
                priority=h.priority,
                name=h.name,
                isolated=True if isolate else h.isolated,
                skip_in_dry_run=h.skip_in_dry_run,
            )

    def clear(self) -> None:
        """Drop every subscription. Test isolation only."""
        self._hooks.clear()
        self._counter = 0


_default_bus = EventBus()


def get_default_bus() -> EventBus:
    """Return the shared module-level bus (used by ``@on``)."""
    return _default_bus


def reset_default_bus() -> None:
    """Test helper: clear every ``@on``-registered hook on the default bus."""
    _default_bus.clear()


def on(phase: Phase, *, priority: int = 100, name: str | None = None):
    """Decorator: register against the module-level default bus.

    Plugin ``hooks.py`` modules use this to subscribe to lifecycle phases.
    The registry's ``hooks.py`` loader runs each plugin's module once at
    startup, after which each verb's ``register_builtin_*_hooks`` splices
    the default bus's accumulated subscriptions onto its own per-run bus.
    """
    def decorator(fn: HookFn) -> HookFn:
        _default_bus.subscribe(phase, fn, priority=priority, name=name)
        return fn
    return decorator
