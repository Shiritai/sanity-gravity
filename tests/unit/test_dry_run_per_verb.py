"""Per-verb dry-run integration tests.

Each kernelized verb (``build`` / ``down`` / ``snapshot`` / ``up``)
must, when invoked with ``dry_run=True``, queue its work and execute
none of it. The Executor's short-circuit (emit ``WouldExecute`` instead
of calling ``action.execute``) is what makes this safe; these tests pin
the contract end-to-end.

Approach: guard the two boundaries a verb can reach the OS through, and
assert on RECORDS rather than on raised exceptions.

- ``SystemRuntime`` is the chokepoint every Action funnels through.
  Patching ``subprocess.run`` alone was not enough: ``SystemRuntime``'s
  ``capture=False`` branch calls ``subprocess.call``, which was never
  patched, so a dry-run regression really did start containers from
  inside this test file.
- ``core.proc`` (``fake_proc``) is the other boundary, used by the
  verbs' own pre-flight probes.

Assertions are on the recorded call lists because the Executor wraps
``action.execute`` in ``except Exception`` -- a guard that merely raised
would be converted into an ActionResult and then into a SystemExit the
test swallows, which is exactly how the ``down`` and ``snapshot`` cases
here used to stay green while the short-circuit was removed.

Each case also asserts the verb actually PLANNED work: "executed
nothing" is trivially true of a verb that did nothing at all.
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sanity_gravity.effects.actions import ActionResult, SystemRuntime
from sanity_gravity.effects.executor import Executor

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class _DryRunGuard:
    """Records what a verb planned and what (if anything) it executed."""

    def __init__(self) -> None:
        self.executed: list[tuple] = []
        self.planned: list = []

    def assert_dry(self) -> None:
        assert self.planned, (
            "the verb queued no actions at all; 'executed nothing' would be "
            "vacuously true, so this case cannot detect a dry-run regression"
        )
        assert self.executed == [], (
            "dry-run executed real side effects:\n  "
            + "\n  ".join(" ".join(map(str, c)) for c in self.executed)
        )


@pytest.fixture
def guard(monkeypatch):
    g = _DryRunGuard()

    # Record instead of raise: the Executor swallows exceptions from
    # execute() into an ActionResult, so a raising double would be
    # invisible here. A benign rc=0 keeps the verb on its normal path.
    def record_subprocess(self, argv, *, env=None, cwd=None, capture=False):
        g.executed.append(tuple(str(a) for a in argv))
        return ActionResult(exit_code=0)

    monkeypatch.setattr(SystemRuntime, "run_subprocess", record_subprocess)
    monkeypatch.setattr(
        SystemRuntime, "write_file",
        lambda self, path, content, mode: g.executed.append(("write_file", path)),
    )
    monkeypatch.setattr(
        SystemRuntime, "make_dirs",
        lambda self, path, mode: g.executed.append(("make_dirs", path)),
    )
    monkeypatch.setattr(SystemRuntime, "sleep", lambda self, seconds: None)

    orig_run = Executor.run

    def spy_run(self, action, *, phase=None):
        g.planned.append(action)
        return orig_run(self, action, phase=phase)

    monkeypatch.setattr(Executor, "run", spy_run)

    # Defence in depth: nothing in a dry run may reach the OS by any
    # other route either. Every legitimate path goes through the two
    # boundaries above or through fake_proc.
    def _forbidden(name):
        def _boom(*a, **kw):
            raise AssertionError(f"subprocess.{name} called in dry-run: {a[:1]}")
        return _boom

    for name in ("run", "call", "check_call", "check_output", "Popen"):
        monkeypatch.setattr(subprocess, name, _forbidden(name))

    return g


@pytest.fixture
def reporter(tmp_path):
    """Real reporter with sinks routed to tmp_path so we don't pollute
    the user's cache dir."""
    from sanity_gravity.core.reporter import build_default_reporter
    rep = build_default_reporter(log_format="text", base=tmp_path / "runs")
    yield rep
    rep.close()


def test_build_dry_run_no_subprocess(reporter, guard, fake_proc, monkeypatch):
    # Build needs to find sandbox/Dockerfile.base; run from the real
    # repo root rather than tmp_path. Dry-run is the operative
    # property, not isolation of the working tree.
    monkeypatch.chdir(_REPO_ROOT)
    from sanity_gravity.verbs import build as build_mod

    args = argparse.Namespace(
        no_cache=False,
        list_intermediates=False,
        layer=None,
        layer_target=None,
        variant=["ag-xfce-kasm"],
        dry_run=True,
        json_output=False,
        reporter=reporter,
    )
    # Must not raise - dry-run short-circuits every action.
    build_mod.build(args)
    guard.assert_dry()
    # The build plan really is docker work that was not done.
    assert any("docker" in " ".join(map(str, a.argv))
               for a in guard.planned if hasattr(a, "argv"))


def test_down_dry_run_no_subprocess(reporter, guard, fake_proc, tmp_path,
                                    monkeypatch):
    monkeypatch.chdir(tmp_path)
    from sanity_gravity.verbs import lifecycle as lc_mod

    args = argparse.Namespace(
        name="proj-test", dry_run=True, reporter=reporter,
    )
    # ``down(args)`` sets check_existence=True; in dry-run the
    # EXISTENCE_CHECK hook short-circuits, so no docker ps is issued
    # either -- an unscripted one would raise from fake_proc.
    lc_mod.down(args)
    guard.assert_dry()
    assert guard.planned[0].argv[-1] == "down"
    fake_proc.assert_never_ran("docker")


def test_snapshot_dry_run_no_subprocess(reporter, guard, fake_proc, tmp_path,
                                        monkeypatch):
    monkeypatch.chdir(tmp_path)
    from sanity_gravity.verbs import snapshot as sn_mod

    args = argparse.Namespace(
        name="proj-test", tag="newtag", variant="ag-xfce-kasm",
        dry_run=True, reporter=reporter,
    )
    sn_mod.snapshot_cmd(args)
    guard.assert_dry()
    # The commit is the whole point of the verb: it must have been
    # planned (and, per assert_dry, not run).
    assert any("commit" in tuple(a.argv)
               for a in guard.planned if hasattr(a, "argv"))


def test_up_dry_run_no_subprocess(reporter, guard, fake_proc, tmp_path,
                                  monkeypatch):
    monkeypatch.chdir(tmp_path)
    from sanity_gravity.verbs import up as up_mod

    args = argparse.Namespace(
        variant="ag-xfce-kasm",
        skip_check=True,
        workspace=str(tmp_path / "ws"),
        name="proj-test",
        ssh_port="2222", kasm_port="8444",
        vnc_port="5901", novnc_port="6901",
        password="pw", cpus=None, memory=None, image=None,
        reporter=reporter,
        dry_run=True,
    )
    # The git-compose hook probes ProxyManager.is_enabled, which really
    # shells out to systemctl (previously the shadow run_command's bare
    # except swallowed this very AssertionError and faked False). Stub
    # the manager: the property under test is the verb's dry-run, not
    # the host's systemd state.
    fake_pm = MagicMock()
    fake_pm.is_enabled.return_value = False
    monkeypatch.setattr(
        "sanity_gravity.compose.generators.ProxyManager",
        lambda *a, **kw: fake_pm,
    )
    monkeypatch.setattr(
        "sanity_gravity.verbs.up.get_uid_gid_user",
        lambda: (1000, 1000, "u"),
    )

    up_mod.up(args)
    guard.assert_dry()
    # ``docker compose ... up -d`` is the action the verb exists to run.
    assert any(
        "up" in tuple(a.argv) and "-d" in tuple(a.argv)
        for a in guard.planned if hasattr(a, "argv")
    )
