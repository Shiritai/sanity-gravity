"""Tests for the Action type hierarchy (PR #5)."""
from __future__ import annotations

import pytest


from sanity_gravity.effects.actions import (
    Action,
    ActionFailedError,
    ActionResult,
    MakeDirs,
    RunSubprocess,
    SystemRuntime,
    WaitForUserInContainer,
    WriteFile,
)


# ---------------------------------------------------------------------------
# FakeRuntime: records calls without touching the system.
# ---------------------------------------------------------------------------


class FakeRuntime:
    def __init__(self, *, sub_results=None, now_seq=None):
        self.subprocess_calls: list[dict] = []
        self.writes: list[tuple[str, str, int]] = []
        self.dirs: list[tuple[str, int]] = []
        self.sleeps: list[float] = []
        self._sub_results = list(sub_results or [])
        self._now_seq = list(now_seq or [0.0, 1.0, 2.0, 3.0, 4.0])

    def run_subprocess(self, argv, *, env, cwd, capture, check, shell):
        self.subprocess_calls.append({
            "argv": argv, "env": dict(env) if env else None,
            "cwd": cwd, "capture": capture, "check": check, "shell": shell,
        })
        if self._sub_results:
            return self._sub_results.pop(0)
        return ActionResult(exit_code=0)

    def write_file(self, path, content, mode):
        self.writes.append((path, content, mode))

    def make_dirs(self, path, mode):
        self.dirs.append((path, mode))

    def sleep(self, seconds):
        self.sleeps.append(seconds)

    def now(self):
        if self._now_seq:
            return self._now_seq.pop(0)
        return 999.0


# ---------------------------------------------------------------------------
# explain() stability
# ---------------------------------------------------------------------------


def test_run_subprocess_explain_quotes_argv():
    a = RunSubprocess(argv=("docker", "compose", "-p", "my proj", "up", "-d"))
    # ``my proj`` carries a space → must be quoted.
    assert "'my proj'" in a.explain()
    assert a.explain().startswith("docker compose -p")


def test_run_subprocess_explain_shell_str():
    a = RunSubprocess(argv=(), shell_str="tar -cf - . | docker exec -i c tar -xf -")
    assert a.explain().startswith("sh -c ")
    assert "tar -cf -" in a.explain()


def test_write_file_explain():
    a = WriteFile(path="/tmp/x.yml", content="hello", mode=0o600)
    assert a.explain() == "write /tmp/x.yml (5 bytes, mode=0o600)"


def test_make_dirs_explain():
    a = MakeDirs(path="/tmp/with space", mode=0o755)
    assert "'/tmp/with space'" in a.explain()


def test_wait_for_user_explain():
    a = WaitForUserInContainer(container="c1", username="dev", timeout_s=10)
    assert "wait-for-user" in a.explain() and "dev" in a.explain()


# ---------------------------------------------------------------------------
# execute() via FakeRuntime
# ---------------------------------------------------------------------------


def test_run_subprocess_execute_records_argv():
    rt = FakeRuntime(sub_results=[ActionResult(exit_code=0, stdout="ok")])
    a = RunSubprocess(argv=("docker", "ps"), capture=True)
    res = a.execute(rt)
    assert res.exit_code == 0 and res.stdout == "ok"
    assert rt.subprocess_calls[0]["argv"] == ("docker", "ps")
    assert rt.subprocess_calls[0]["shell"] is False


def test_run_subprocess_shell_str_routes_via_shell_true():
    rt = FakeRuntime()
    a = RunSubprocess(argv=(), shell_str="echo hi | cat")
    a.execute(rt)
    assert rt.subprocess_calls[0]["shell"] is True
    assert rt.subprocess_calls[0]["argv"] == "echo hi | cat"


def test_write_file_calls_runtime():
    rt = FakeRuntime()
    a = WriteFile(path="/tmp/a", content="data", mode=0o644)
    a.execute(rt)
    assert rt.writes == [("/tmp/a", "data", 0o644)]


def test_make_dirs_calls_runtime():
    rt = FakeRuntime()
    a = MakeDirs(path="/tmp/d")
    a.execute(rt)
    assert rt.dirs == [("/tmp/d", 0o755)]


def test_wait_for_user_returns_when_id_succeeds():
    # First call: no digit; second call: returns "1000".
    rt = FakeRuntime(
        sub_results=[
            ActionResult(exit_code=1, stderr="no such user"),
            ActionResult(exit_code=0, stdout="1000"),
        ],
        now_seq=[0.0, 0.5, 1.0, 1.5, 2.0],
    )
    a = WaitForUserInContainer(container="c", username="dev", timeout_s=10)
    res = a.execute(rt)
    assert res.exit_code == 0
    assert "1000" in res.stdout
    assert rt.sleeps == [1.0]  # slept once between attempts


def test_wait_for_user_times_out():
    rt = FakeRuntime(
        sub_results=[ActionResult(exit_code=1, stderr="no")] * 5,
        now_seq=[0.0, 0.0, 5.0, 11.0],  # deadline = 10
    )
    a = WaitForUserInContainer(container="c", username="dev", timeout_s=10)
    res = a.execute(rt)
    assert res.exit_code == 1
    assert "no" in res.stderr or "timeout" in res.stderr


# ---------------------------------------------------------------------------
# ActionFailedError
# ---------------------------------------------------------------------------


def test_action_failed_error_carries_action_and_result():
    a = RunSubprocess(argv=("false",))
    res = ActionResult(exit_code=2, stderr="nope")
    err = ActionFailedError(a, res, phase="up.docker", hint="check ports")
    assert err.action is a
    assert err.result.exit_code == 2
    assert err.phase == "up.docker"
    assert err.hint == "check ports"
    assert "false" in str(err)


# ---------------------------------------------------------------------------
# SystemRuntime sanity (only smoke: a trivial true/false, no docker)
# ---------------------------------------------------------------------------


def test_system_runtime_runs_true():
    rt = SystemRuntime()
    res = rt.run_subprocess(("true",), env=None, cwd=None,
                            capture=True, check=False, shell=False)
    assert res.exit_code == 0


def test_system_runtime_makedirs_and_write(tmp_path):
    rt = SystemRuntime()
    sub = tmp_path / "a" / "b"
    rt.make_dirs(str(sub), 0o755)
    assert sub.is_dir()
    target = sub / "x.txt"
    rt.write_file(str(target), "hello", 0o644)
    assert target.read_text() == "hello"
