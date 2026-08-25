"""Tests for the lifecycle verbs' microkernel migration (PR #7b).

Covers down/stop/start/restart and clean. We patch ``get_active_projects``
and ``get_project_env`` so the tests don't touch docker.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from sanity_gravity.core.eventbus import EventBus
from sanity_gravity.core.orchestrator import (
    _LIFECYCLE_PHASES,
    CleanContext,
    DownContext,
    Orchestrator,
)
from sanity_gravity.core.reporter import Reporter
from sanity_gravity.domain.phase import Phase
from sanity_gravity.effects.actions import RunSubprocess
from sanity_gravity.hooks.lifecycle import (
    register_builtin_lifecycle_hooks,
)


def _reporter():
    return Reporter(sinks=[], run_id="test")


def _ctx(action="down", project="my-proj", **kw):
    kw.setdefault("dry_run", True)
    return DownContext(
        project=project, action=action, reporter=_reporter(), **kw,
    )


@pytest.fixture(autouse=True)
def _stub_lifecycle_helpers(fake_proc):
    """Stub the docker-touching helpers in lifecycle_hooks.

    Lifecycle verbs no longer scan ``config/`` for compose files (they
    resolve containers purely via the ``-p <project>`` label), so there
    is nothing compose-file-related to stub anymore.

    ``fake_proc`` is pulled in with nothing scripted on purpose: these
    tests drive the kernel with a fake executor and stubbed discovery
    helpers, so NO command should reach the subprocess boundary at all.
    Any that did would raise UnscriptedCommand rather than quietly
    shelling out to the host's docker.
    """
    with patch(
        "sanity_gravity.verbs.lifecycle.get_active_projects",
        return_value=["my-proj"],
    ), patch(
        "sanity_gravity.verbs.lifecycle.get_project_env",
        return_value={"HOST_USER": "dev"},
    ):
        yield


def test_down_phase_sequence_runs_in_order():
    bus = EventBus()
    fired: list[Phase] = []
    for ph in _LIFECYCLE_PHASES:
        bus.subscribe(ph, lambda ctx, p=ph: fired.append(p))
    ctx = _ctx()
    Orchestrator(bus, ctx.reporter).run(_LIFECYCLE_PHASES, ctx)
    assert fired == list(_LIFECYCLE_PHASES)


def test_down_enqueues_compose_down_action():
    bus = EventBus()
    register_builtin_lifecycle_hooks(bus)
    ctx = _ctx(action="down", check_existence=True)

    captured: list = []

    class _Exec:
        def drain(self, actions, phase=None):
            captured.extend(actions)

    Orchestrator(bus, ctx.reporter, executor=_Exec()).run(_LIFECYCLE_PHASES, ctx)
    assert len(captured) == 1
    a = captured[0]
    assert isinstance(a, RunSubprocess)
    assert a.argv[:4] == ("docker", "compose", "-p", "my-proj")
    assert a.argv[-1] == "down"


def test_stop_action_uses_stop_verb():
    bus = EventBus()
    register_builtin_lifecycle_hooks(bus)
    ctx = _ctx(action="stop")

    captured: list = []

    class _Exec:
        def drain(self, actions, phase=None):
            captured.extend(actions)

    Orchestrator(bus, ctx.reporter, executor=_Exec()).run(_LIFECYCLE_PHASES, ctx)
    assert captured[0].argv[-1] == "stop"


def test_down_with_check_existence_bails_when_project_missing():
    """``down -n nonexistent`` should not enqueue any docker action.

    This tests the *real* (non dry-run) existence check; the dry-run
    path explicitly skips the check (see ``lifecycle_check_existence``)
    so we set ``dry_run=False`` here to exercise it.
    """
    bus = EventBus()
    register_builtin_lifecycle_hooks(bus)
    ctx = _ctx(
        action="down", check_existence=True,
        project="does-not-exist", dry_run=False,
    )

    captured: list = []

    class _Exec:
        def drain(self, actions, phase=None):
            captured.extend(actions)

    Orchestrator(bus, ctx.reporter, executor=_Exec()).run(_LIFECYCLE_PHASES, ctx)
    assert captured == []


def test_down_dry_run_skips_existence_check():
    """In dry-run mode, the existence check is skipped entirely so the
    verb does not shell out to ``docker ps`` (which can hang or write
    audit log entries the user did not consent to). The compose action
    is still enqueued — the executor short-circuits it as
    ``WouldExecute``."""
    bus = EventBus()
    register_builtin_lifecycle_hooks(bus)
    ctx = _ctx(
        action="down", check_existence=True,
        project="does-not-exist", dry_run=True,
    )

    # If the existence check fired, ``get_active_projects`` would be
    # called. ``_stub_lifecycle_helpers`` already patches it; we rely
    # on the guard to skip even calling the patched version.
    captured: list = []

    class _Exec:
        def drain(self, actions, phase=None):
            captured.extend(actions)

    Orchestrator(bus, ctx.reporter, executor=_Exec()).run(_LIFECYCLE_PHASES, ctx)
    # The compose action is enqueued (and would-execute'd by the real
    # executor); we just check the hook didn't bail prematurely.
    assert len(captured) == 1
    assert captured[0].argv[-1] == "down"


def test_clean_appends_extra_compose_args():
    bus = EventBus()
    register_builtin_lifecycle_hooks(bus)
    ctx = CleanContext(
        project="my-proj",
        action="down",
        reporter=_reporter(),
        check_existence=False,
        dry_run=True,
        extra_action_args=("-v", "--rmi", "local", "--remove-orphans"),
        force=True,
    )

    captured: list = []

    class _Exec:
        def drain(self, actions, phase=None):
            captured.extend(actions)

    Orchestrator(bus, ctx.reporter, executor=_Exec()).run(_LIFECYCLE_PHASES, ctx)
    assert len(captured) == 1
    argv = captured[0].argv
    # Tail must be: down -v --rmi local --remove-orphans
    assert argv[-5:] == ("down", "-v", "--rmi", "local", "--remove-orphans")


def test_clean_cancelled_when_user_says_no(monkeypatch):
    """The interactive prompt path should set ctx.cancelled and skip docker."""
    bus = EventBus()
    register_builtin_lifecycle_hooks(bus)
    # Pretend stdin is a TTY and user typed 'n'.
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a, **kw: "n")

    ctx = CleanContext(
        project="my-proj",
        action="down",
        reporter=_reporter(),
        dry_run=True,
        extra_action_args=("-v", "--rmi", "local", "--remove-orphans"),
        force=False,
    )

    captured: list = []

    class _Exec:
        def drain(self, actions, phase=None):
            captured.extend(actions)

    Orchestrator(bus, ctx.reporter, executor=_Exec()).run(_LIFECYCLE_PHASES, ctx)
    assert ctx.cancelled is True
    assert captured == []
