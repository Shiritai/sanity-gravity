"""Tests for the Action Executor (PR #5)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sanity_gravity.domain.phase import Phase
from sanity_gravity.effects.actions import (
    ActionFailedError,
    ActionResult,
    MakeDirs,
    RunSubprocess,
    WriteFile,
)
from sanity_gravity.effects.executor import Executor
from sanity_gravity.events import (
    ActionFailed,
    ActionFinished,
    ActionStarted,
    WouldExecute,
)

# ---------------------------------------------------------------------------
# Capturing fakes
# ---------------------------------------------------------------------------


class CaptureReporter:
    """Reporter stand-in that just appends every emitted Event."""

    def __init__(self):
        self.run_id = "exec-test"
        self.events = []

    def emit(self, event):
        self.events.append(event)

    def emit_now(self, event_cls, *, level="info", phase=None, **payload):
        # Match Reporter.emit_now: stamp ts/run_id/phase/level on the
        # event so executor tests don't have to plumb them through.
        self.events.append(event_cls(
            ts=0.0, run_id=self.run_id, phase=phase, level=level, **payload,
        ))


class FakeRuntime:
    """Fake runtime that returns pre-canned ActionResult objects."""

    def __init__(self, *, sub_results=None):
        self.subprocess_calls = []
        self.writes = []
        self.dirs = []
        self._sub_results = list(sub_results or [])

    def run_subprocess(self, argv, *, env, cwd, capture):
        self.subprocess_calls.append(argv)
        if self._sub_results:
            return self._sub_results.pop(0)
        return ActionResult(exit_code=0, duration_ms=1)

    def write_file(self, path, content, mode):
        self.writes.append((path, content, mode))

    def make_dirs(self, path, mode):
        self.dirs.append((path, mode))

    def sleep(self, seconds): pass

    def now(self): return 0.0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_executor_runs_action_and_emits_started_finished():
    rt = FakeRuntime(sub_results=[ActionResult(exit_code=0, duration_ms=12)])
    rep = CaptureReporter()
    ex = Executor(runtime=rt, reporter=rep)
    a = RunSubprocess(argv=("docker", "ps"))
    res = ex.run(a, phase=Phase.UP_DOCKER)

    assert res.exit_code == 0
    assert rt.subprocess_calls == [("docker", "ps")]
    types = [type(e).__name__ for e in rep.events]
    assert types == ["ActionStarted", "ActionFinished"]
    started, finished = rep.events
    assert isinstance(started, ActionStarted)
    assert started.argv == ("docker", "ps")
    assert started.action_type == "RunSubprocess"
    assert started.phase == "up.docker"
    assert isinstance(finished, ActionFinished)
    assert finished.exit_code == 0


def test_executor_dry_run_emits_would_execute_only():
    rt = FakeRuntime()
    rep = CaptureReporter()
    ex = Executor(runtime=rt, reporter=rep, dry_run=True)
    a = RunSubprocess(argv=("docker", "compose", "up", "-d"))
    ex.run(a, phase=Phase.UP_DOCKER)

    # No subprocess call happened.
    assert rt.subprocess_calls == []
    assert len(rep.events) == 1
    ev = rep.events[0]
    assert isinstance(ev, WouldExecute)
    assert "docker compose up -d" in ev.explain_str


def test_executor_failure_raises_and_emits_action_failed():
    rt = FakeRuntime(sub_results=[ActionResult(
        exit_code=125, stderr="port already in use", duration_ms=5,
    )])
    rep = CaptureReporter()
    ex = Executor(runtime=rt, reporter=rep)
    a = RunSubprocess(argv=("docker", "compose", "up"))

    with pytest.raises(ActionFailedError) as excinfo:
        ex.run(a, phase=Phase.UP_DOCKER)

    err = excinfo.value
    assert err.result.exit_code == 125
    types = [type(e).__name__ for e in rep.events]
    assert "ActionStarted" in types
    assert "ActionFinished" in types
    assert "ActionFailed" in types
    failed = [e for e in rep.events if isinstance(e, ActionFailed)][0]
    assert failed.exit_code == 125
    assert "port already in use" in failed.stderr_tail


def test_executor_check_false_does_not_raise():
    rt = FakeRuntime(sub_results=[ActionResult(exit_code=1)])
    rep = CaptureReporter()
    ex = Executor(runtime=rt, reporter=rep)
    a = RunSubprocess(argv=("docker", "inspect", "nope"), check=False)
    res = ex.run(a)
    assert res.exit_code == 1
    # No ActionFailed should be emitted for check=False actions.
    assert not any(isinstance(e, ActionFailed) for e in rep.events)


def test_executor_drain_runs_in_order_and_stops_on_failure():
    rt = FakeRuntime(sub_results=[
        ActionResult(exit_code=0),
        ActionResult(exit_code=1, stderr="boom"),
        ActionResult(exit_code=0),
    ])
    rep = CaptureReporter()
    ex = Executor(runtime=rt, reporter=rep)
    actions = [
        RunSubprocess(argv=("a",)),
        RunSubprocess(argv=("b",)),
        RunSubprocess(argv=("c",)),  # should not run
    ]
    with pytest.raises(ActionFailedError):
        ex.drain(actions)
    # Ran a and b, not c.
    assert rt.subprocess_calls == [("a",), ("b",)]
    # Both attempts recorded in history.
    assert len(ex.history) == 2


def test_executor_writes_actions_jsonl(tmp_path):
    rt = FakeRuntime(sub_results=[ActionResult(exit_code=0, duration_ms=7)])
    rep = CaptureReporter()
    ex = Executor(runtime=rt, reporter=rep, run_dir=tmp_path)
    a = RunSubprocess(argv=("docker", "ps"))
    ex.run(a, phase=Phase.UP_DOCKER)
    ex.close()

    log = (tmp_path / "actions.jsonl").read_text().strip().splitlines()
    assert len(log) == 1
    payload = json.loads(log[0])
    assert payload["phase"] == "up.docker"
    assert payload["action_type"] == "RunSubprocess"
    assert payload["argv"] == ["docker", "ps"]
    assert payload["result"]["exit"] == 0
    assert payload["dry_run"] is False


def test_executor_dry_run_logs_with_flag(tmp_path):
    rt = FakeRuntime()
    rep = CaptureReporter()
    ex = Executor(runtime=rt, reporter=rep, dry_run=True, run_dir=tmp_path)
    ex.run(RunSubprocess(argv=("docker", "ps")), phase=Phase.UP_DOCKER)
    ex.close()
    log = json.loads((tmp_path / "actions.jsonl").read_text().splitlines()[0])
    assert log["dry_run"] is True


def test_executor_handles_writefile_makedirs():
    rt = FakeRuntime()
    rep = CaptureReporter()
    ex = Executor(runtime=rt, reporter=rep)
    ex.run(MakeDirs(path="/tmp/x"), phase=Phase.UP_PROVISION)
    ex.run(WriteFile(path="/tmp/x/y", content="z"), phase=Phase.UP_PROVISION)
    assert rt.dirs == [("/tmp/x", 0o755)]
    assert rt.writes == [("/tmp/x/y", "z", 0o644)]


# ---------------------------------------------------------------------------
# End-to-end: full up flow under dry-run does not invoke the subprocess.
# ---------------------------------------------------------------------------


def test_full_up_flow_dry_run_makes_no_subprocess_calls():
    """A dry-run up flow should not invoke any subprocess."""
    from sanity_gravity.core.eventbus import EventBus
    from sanity_gravity.core.orchestrator import (  # noqa: PLC0415
        _UP_PHASES,
        Deps,
        Orchestrator,
        PortRequest,
        RequestedPort,
        UpContext,
    )
    from sanity_gravity.core.proc import Completed
    from sanity_gravity.domain.tags import Tag  # noqa: PLC0415
    from sanity_gravity.hooks.up import register_builtin_up_hooks  # noqa: PLC0415

    bus = EventBus()
    register_builtin_up_hooks(bus)

    deps = Deps(
        validate_username=lambda u: u,
        validate_project_name=lambda p: p,
        generate_compose_for_tag=lambda t: ("config/foo.yml", t),
        generate_git_compose=lambda u, s: None,
        generate_resource_compose=lambda c, m, s: None,
        sync_config=lambda *a, **kw: None,
        is_port_in_use=lambda p: False,
        try_run=lambda *a, **kw: Completed((), 0),  # docker goes via Action
    )

    rep = CaptureReporter()
    # Reporter needs ``info`` for phase-tick lines + a few convenience
    # builders the hooks call directly.
    rep.info = lambda *a, **kw: None
    rep.warning = lambda *a, **kw: None
    rep.success = lambda *a, **kw: None
    rep.access = lambda *a, **kw: None
    rep.error = lambda *a, **kw: None
    rep.header = lambda *a, **kw: None

    ctx = UpContext(
        tag=Tag(agent="ag", desktop="xfce", connector="kasm"),
        project="sanity-gravity",
        host_user="dev",
        host_uid=1000,
        host_gid=1000,
        password="x",
        workspace=Path("/tmp/ws"),
        image_override=None,
        requested_ports=PortRequest(entries={
            "ssh": RequestedPort("2222"),
            "kasm": RequestedPort("8444"),
            "vnc": RequestedPort("5901"),
            "novnc": RequestedPort("6901"),
        }),
        deps=deps,
        reporter=rep,
    )

    rt = FakeRuntime()
    ex = Executor(runtime=rt, reporter=rep, dry_run=True)
    Orchestrator(bus, rep, executor=ex).run(_UP_PHASES, ctx)

    # No subprocess calls under dry-run.
    assert rt.subprocess_calls == []
    # At least one WouldExecute event for the compose-up.
    would = [e for e in rep.events if isinstance(e, WouldExecute)]
    assert any("compose" in e.explain_str for e in would)
