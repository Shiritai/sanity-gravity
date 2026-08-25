"""Microkernel orchestrator + verb-specific contexts.

This module defines :class:`Orchestrator` — the generic phase-loop
driver — plus the per-verb mutable contexts (``UpContext``,
``BuildContext``, ``DownContext``, ``CleanContext``,
``SnapshotContext``). Builtin hook implementations for each verb live
under :mod:`sanity_gravity.hooks`; this file is just orchestration glue.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sanity_gravity.core.eventbus import EventBus
from sanity_gravity.core.proc import Completed
from sanity_gravity.domain.naming import Naming
from sanity_gravity.domain.phase import Phase
from sanity_gravity.domain.tags import Tag
from sanity_gravity.effects.actions import Action


@dataclass(frozen=True)
class RequestedPort:
    """One requested host port + whether an explicit CLI flag set it."""

    value: str
    explicit: bool = False


@dataclass
class PortRequest:
    """User's desired host ports, keyed by runtime port slug.

    Slugs match ``PortSpec.legacy_slug`` (or the port label when the
    manifest omits it). The CLI adapter in ``verbs/up.py`` maps its
    static ``--*-port`` flags onto slugs; ``auto_port_alloc`` merges
    these requests with the manifest-declared port specs, so the kernel
    itself carries no per-connector port table.
    """

    entries: dict[str, RequestedPort] = field(default_factory=dict)


@dataclass
class Deps:
    """Injected helpers. Tests swap any of these for stubs."""

    validate_username: Callable[[str], str]
    validate_project_name: Callable[[str], str]
    generate_compose_for_tag: Callable[[str], tuple[str, str]]
    generate_git_compose: Callable[[str, str], str | None]
    generate_resource_compose: Callable[[str | None, str | None, str], str | None]
    sync_config: Callable[[str, str, str], None]
    is_port_in_use: Callable[[int], bool]
    try_run: Callable[..., Completed]


@dataclass
class UpContext:
    """Mutable context carried across all up phases."""

    tag: Tag
    project: str
    host_user: str
    host_uid: int
    host_gid: int
    password: str
    workspace: Path
    image_override: str | None
    requested_ports: PortRequest
    deps: Deps
    reporter: Any  # lib.reporter.Reporter; left untyped to avoid cycle
    resolved_ports: dict[str, str] = field(default_factory=dict)
    compose_files: list[Path] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    extra_compose_overlays: list[Any] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    dry_run: bool = False

    def drain_actions(self) -> list[Action]:
        """Pop and return the queued actions, leaving the list empty.

        Called by :class:`Orchestrator` after each phase publish so the
        Executor runs them in order before the next phase begins.
        """
        out = list(self.actions)
        self.actions.clear()
        return out

    @property
    def naming(self) -> Naming:
        """Single generator for every name hooks derive from this ctx."""
        return Naming(self.tag, self.project)

    @property
    def service_name(self) -> str:
        return self.naming.service()

    @property
    def container_name(self) -> str:
        return self.naming.container()


_UP_PHASES: tuple[Phase, ...] = (
    Phase.UP_VALIDATE,
    Phase.UP_COMPOSE,
    Phase.UP_PORT_ALLOC,
    Phase.UP_DOCKER,
    Phase.UP_PROVISION,
    Phase.UP_ANNOUNCE,
)

# Phase sequences for the other kernelized verbs. These live next to
# ``_UP_PHASES`` so the entire phase topology is auditable from one place.

_BUILD_PHASES: tuple[Phase, ...] = (
    Phase.BUILD_PLAN,
    Phase.BUILD_LAYER,
    Phase.BUILD_DONE,
)

_LIFECYCLE_PHASES: tuple[Phase, ...] = (
    Phase.LIFECYCLE_BEFORE,
    Phase.LIFECYCLE_DOCKER,
    Phase.LIFECYCLE_AFTER,
)

_SNAPSHOT_PHASES: tuple[Phase, ...] = (
    Phase.SNAPSHOT_PLAN,
    Phase.SNAPSHOT_DOCKER,
    Phase.SNAPSHOT_DONE,
)


class Orchestrator:
    """Generic phase-loop driver.

    Iterates a phase sequence; for each phase it (a) emits a subtle
    ``[<phase>]`` tick line so a slow run shows progress, (b) publishes
    the phase event so subscribed hooks fire in priority order, and (c)
    drains any actions the hooks enqueued onto the ctx through the
    executor before advancing to the next phase.

    Hooks are dispatched one at a time and the action queue is drained
    *between* hooks within the same phase: a later hook (e.g. one that
    reads docker state back) must observe state produced by the actions
    of earlier hooks in the same phase.
    """

    def __init__(
        self,
        bus: EventBus,
        reporter: Any,
        executor: Any | None = None,
    ) -> None:
        self.bus = bus
        self.reporter = reporter
        self.executor = executor

    def __enter__(self) -> Orchestrator:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self.executor is not None:
            self.executor.close()

    def _on_isolated_error(self, hook: Any, exc: BaseException) -> None:
        """Log a plugin hook's failure to the reporter without re-raising."""
        name = getattr(hook, "name", None) or "<anon>"
        phase_value = getattr(getattr(hook, "phase", None), "value", "<?>")
        self.reporter.warning(
            f"plugin hook {name!r} raised on phase {phase_value}: "
            f"{type(exc).__name__}: {exc}"
        )

    def run(self, phases: Sequence[Phase], ctx: Any) -> None:
        dry_run = bool(getattr(ctx, "dry_run", False))
        for phase in phases:
            self.reporter.info(f"[{phase.value}]")
            hooks = self.bus.hooks_for(phase) if hasattr(self.bus, "hooks_for") else None
            if hooks is None:
                self.bus.publish(
                    phase, ctx, on_isolated_error=self._on_isolated_error,
                )
            else:
                for hook in hooks:
                    # Hooks marked ``skip_in_dry_run`` are pure
                    # side-effect with nothing to preview; the
                    # orchestrator drops them in dry-run mode rather
                    # than relying on each hook to check ``ctx.dry_run``
                    # internally.
                    if dry_run and getattr(hook, "skip_in_dry_run", False):
                        continue
                    if getattr(hook, "isolated", False):
                        # Snapshot the actions queue so a half-failed hook's
                        # already-appended actions can be discarded — running
                        # them would defeat the point of isolation.
                        # ``Exception`` (not ``BaseException``) so SystemExit
                        # / KeyboardInterrupt still abort the run.
                        actions_attr = getattr(ctx, "actions", None)
                        baseline = (
                            len(actions_attr)
                            if isinstance(actions_attr, list) else None
                        )
                        try:
                            hook.fn(ctx)
                        except Exception as exc:  # plugin-contributed
                            if baseline is not None:
                                # Drop anything this hook added before raising.
                                del actions_attr[baseline:]
                            self._on_isolated_error(hook, exc)
                    else:
                        hook.fn(ctx)
                    if self.executor is not None and hasattr(ctx, "drain_actions"):
                        pending = ctx.drain_actions()
                        if pending:
                            self.executor.drain(pending, phase=phase)
            # Final drain: catches actions appended by ``publish`` (no
            # hooks_for) or by hooks when no executor is attached at
            # mid-phase time.
            if self.executor is not None and hasattr(ctx, "drain_actions"):
                pending = ctx.drain_actions()
                if pending:
                    self.executor.drain(pending, phase=phase)


# ---------------------------------------------------------------------------
# Per-verb contexts
# ---------------------------------------------------------------------------


@dataclass
class BuildContext:
    """Mutable context for the ``build`` verb's phase loop."""

    targets: list[str]
    reporter: Any
    no_cache: bool = False
    layer_target: str | None = None              # "base" / "desktop" / "agent" / "connector"
    layer_target_specific: str | None = None     # e.g. "xfce" or "ag-xfce"
    list_intermediates: bool = False
    json_output: bool = False
    plan: list = field(default_factory=list)
    # ``plan`` entries are ``PlanNode`` values (sanity_gravity.domain.plan):
    # structural layer identity + dockerfile + context; parent derives
    # from the structure, never from a rendered name.
    actions: list[Action] = field(default_factory=list)
    dry_run: bool = False

    def drain_actions(self) -> list[Action]:
        out = list(self.actions)
        self.actions.clear()
        return out


@dataclass
class DownContext:
    """Mutable context for ``down`` / ``stop`` / ``start`` / ``restart``."""

    project: str
    action: str  # "down" | "stop" | "start" | "restart"
    reporter: Any
    check_existence: bool = False
    project_exists: bool = True
    compose_files: list[Path] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    actions: list[Action] = field(default_factory=list)
    dry_run: bool = False
    # Extra args to append after the action verb on the compose command.
    # ``clean`` uses this to add ``-v --rmi local --remove-orphans``.
    extra_action_args: tuple[str, ...] = ()

    def drain_actions(self) -> list[Action]:
        out = list(self.actions)
        self.actions.clear()
        return out


@dataclass
class CleanContext(DownContext):
    """``clean`` extends ``down`` with extra docker-compose args + force flag."""

    force: bool = False
    cancelled: bool = False  # set by the prompt hook on user 'N'


@dataclass
class SnapshotContext:
    """Mutable context for the ``snapshot`` verb."""

    project: str
    target_tag: str
    reporter: Any
    variant: str | None = None
    container_id: str | None = None
    target_variant: str | None = None
    actions: list[Action] = field(default_factory=list)
    dry_run: bool = False
    cancelled: bool = False  # multi-variant prompt may bail

    def drain_actions(self) -> list[Action]:
        out = list(self.actions)
        self.actions.clear()
        return out
