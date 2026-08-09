"""Per-verb dry-run integration tests.

Each kernelized verb (``build`` / ``down`` / ``snapshot`` / ``up``)
must, when invoked with ``dry_run=True``, complete without calling
``subprocess.run`` / ``subprocess.check_call``. The Executor's
short-circuit (emit ``WouldExecute`` instead of executing) is what
makes this safe; these tests pin the contract end-to-end.

Approach: install the real reporter + executor + orchestrator wiring,
but patch the *Runtime* layer (``effects.executor.SubprocessRuntime``)
to fail loudly if invoked. In dry-run mode it must NOT be invoked.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))


def _no_subprocess():
    """Patch every subprocess entry point to raise loudly. Returns the
    list of patchers so the caller can unwind after."""
    return (
        patch("subprocess.run",
              side_effect=AssertionError("subprocess.run called in dry-run")),
        patch("subprocess.check_call",
              side_effect=AssertionError("subprocess.check_call called in dry-run")),
        patch("subprocess.check_output",
              side_effect=AssertionError("subprocess.check_output called in dry-run")),
    )


@pytest.fixture
def reporter(tmp_path):
    """Real reporter with sinks routed to tmp_path so we don't pollute
    the user's cache dir."""
    from sanity_gravity.core.reporter import build_default_reporter
    rep = build_default_reporter(log_format="text", base=tmp_path / "runs")
    yield rep
    rep.close()


def test_build_dry_run_no_subprocess(reporter, monkeypatch):
    # Build resolves Dockerfile paths via the manifest registry; run from
    # the real repo root rather than tmp_path. Dry-run is the operative
    # property, not isolation of the working tree.
    monkeypatch.chdir(_REPO_ROOT)
    from sanity_gravity.verbs import build as build_mod

    p1, p2, p3 = _no_subprocess()
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
    with p1, p2, p3:
        # Must not raise — dry-run short-circuits all subprocess calls.
        try:
            build_mod.build(args)
        except SystemExit as ei:
            # Only acceptable failure path: ActionFailedError caught.
            # Even that should not happen in pure dry-run.
            pytest.fail(f"build() exited with code {ei.code} in dry-run")


def test_down_dry_run_no_subprocess(reporter, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from sanity_gravity.verbs import lifecycle as lc_mod

    p1, p2, p3 = _no_subprocess()
    args = argparse.Namespace(
        name="proj-test", dry_run=True, reporter=reporter,
    )
    # The lifecycle verb queries docker for project existence in
    # check_existence mode. ``down(args)`` sets check_existence=True.
    # The check goes through ``run_command``, which uses subprocess —
    # but in dry-run mode the EXISTENCE_CHECK hook also short-circuits.
    # If a regression skips that guard, the test will catch it.
    with p1, p2, p3:
        try:
            lc_mod.down(args)
        except SystemExit:
            pass  # ActionFailedError-induced exit is fine; subprocess
                  # being called would have raised AssertionError first.


def test_snapshot_dry_run_no_subprocess(reporter, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from sanity_gravity.verbs import snapshot as sn_mod

    p1, p2, p3 = _no_subprocess()
    args = argparse.Namespace(
        name="proj-test", tag="newtag", variant="ag-xfce-kasm",
        dry_run=True, reporter=reporter,
    )
    with p1, p2, p3:
        try:
            sn_mod.snapshot_cmd(args)
        except SystemExit:
            pass


def test_up_dry_run_no_subprocess(reporter, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from sanity_gravity.verbs import up as up_mod

    p1, p2, p3 = _no_subprocess()
    # In dry-run we still need basic dependencies to resolve. Stub
    # check_prereqs so it doesn't shell out to docker.
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
    with p1, p2, p3, \
         patch("sanity_gravity.verbs.up.get_uid_gid_user",
               return_value=(1000, 1000, "u")):
        try:
            up_mod.up(args)
        except SystemExit:
            pass
