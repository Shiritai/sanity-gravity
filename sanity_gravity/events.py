"""Event hierarchy for the structured Reporter.

Events are immutable, JSON-serialisable records of one narration site each.
Reporter builds them; Sinks consume them. The visual rendering decision
lives entirely in the Sink — events themselves carry only data.

Design notes
------------
- Every concrete event subclasses ``Event`` and is a frozen dataclass so
  ``dataclasses.asdict(ev)`` round-trips cleanly to JSON.
- The ``phase`` field is forward-compat for PR #4's Phase enum and stays
  ``None`` until then.
- The ``level`` field tags severity for sinks that want to colourise or
  filter (``info`` | ``success`` | ``warning`` | ``error`` | ``header``).
- ``ErrorEvent`` is named with a suffix to avoid shadowing the builtin.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Event:
    """Base class for all reporter events."""

    ts: float
    run_id: str
    phase: str | None = None
    level: str = "info"


@dataclass(frozen=True)
class RunStarted(Event):
    """Marks the beginning of a run.

    Carries no extra payload — the base Event already exposes ``run_id``
    and ``ts``, which is all consumers need. Structured sinks emit it as
    ``{"type": "RunStarted", "run_id": ...}``; the AnsiSink renders it
    as the legacy ``>>> run-id: ...`` banner.
    """


@dataclass(frozen=True)
class Header(Event):
    """A section header (replaces ``print_header``)."""

    message: str = ""


@dataclass(frozen=True)
class Info(Event):
    """An informational line (replaces ``print_info``)."""

    message: str = ""


@dataclass(frozen=True)
class Success(Event):
    """A success line (replaces ``print_success``)."""

    message: str = ""


@dataclass(frozen=True)
class Warning(Event):
    """A warning line (replaces ``print_warning``)."""

    message: str = ""


@dataclass(frozen=True)
class ErrorEvent(Event):
    """An error line (replaces ``print_error``).

    Named ``ErrorEvent`` rather than ``Error`` to avoid shadowing the
    builtin ``Error`` typing in callers.
    """

    message: str = ""


@dataclass(frozen=True)
class CommandIssued(Event):
    """Echoed ``$ cmd`` line emitted by the subprocess boundary
    (:mod:`sanity_gravity.core.proc`) before exec.

    ``argv`` is either a tuple of argv tokens (preferred) or a raw shell
    string for the few legacy ``shell=True`` sites.
    """

    argv: tuple[str, ...] | str = ()


@dataclass(frozen=True)
class CacheHit(Event):
    """A build layer was found cached and skipped."""

    image: str = ""


@dataclass(frozen=True)
class LayerBuilding(Event):
    """A build layer is about to be built; replaces the
    ``[i/n] Building ...`` info line."""

    image: str = ""
    dockerfile: str = ""
    index: int = 0
    total: int = 0


@dataclass(frozen=True)
class LayerBuilt(Event):
    """A build layer completed successfully."""

    image: str = ""


@dataclass(frozen=True)
class AccessInfo(Event):
    """Connection details for a freshly-started service.

    ``connector`` is e.g. ``"kasm"`` / ``"vnc"`` / ``"ssh"``; ``fields``
    is an ordered mapping of human-friendly labels (``"URL"``, ``"SSH"``,
    ``"User"``, ...) to their string values. Sinks decide how to render.
    """

    connector: str = ""
    fields: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Prompt(Event):
    """An interactive prompt about to be shown to the user.

    AnsiSink renders this; JsonlSink ignores it (the prompt itself is
    not part of the structured event stream — only the fact that a
    question was asked).
    """

    question: str = ""


@dataclass(frozen=True)
class ActionStarted(Event):
    """An :class:`~actions.Action` is about to execute."""

    action_type: str = ""
    argv: tuple[str, ...] | str = ()


@dataclass(frozen=True)
class ActionFinished(Event):
    """An Action finished. ``exit_code == 0`` means success."""

    action_type: str = ""
    exit_code: int = 0
    duration_ms: int = 0


@dataclass(frozen=True)
class ActionFailed(Event):
    """An Action returned non-zero. Carries the structured failure context."""

    action_type: str = ""
    argv: tuple[str, ...] | str = ()
    exit_code: int = 0
    stderr_tail: str = ""
    explain_str: str = ""


@dataclass(frozen=True)
class WouldExecute(Event):
    """Emitted under ``--dry-run`` in lieu of running the Action."""

    explain_str: str = ""
    action_type: str = ""
