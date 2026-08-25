"""Verbs no longer end the process: expected failures fly to cli/main.

ActionFailedError is a SanityError (exit_code taken from the action's
result), so the historical per-verb ``try/except -> sys.exit`` wrappers
are gone and the boundary picks the identical exit code from
``e.exit_code``. up's parse / collision aborts raise instead of exiting
for the same reason.
"""
from __future__ import annotations

import argparse
from unittest.mock import patch

import pytest

from sanity_gravity.core.reporter import Reporter
from sanity_gravity.domain.errors import SanityError
from sanity_gravity.effects.actions import (
    ActionFailedError,
    ActionResult,
    RunSubprocess,
)


def _action_error(code=3):
    return ActionFailedError(
        RunSubprocess(argv=("docker", "x")), ActionResult(exit_code=code),
    )


class _RaisingOrch:
    """Context-manager Orchestrator stand-in whose run() fails."""

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, phases, ctx):
        raise _action_error(3)


def _reporter():
    return Reporter(sinks=[], run_id="t")


class TestActionFailedErrorIsSanityError:
    def test_exit_code_comes_from_the_result(self):
        e = _action_error(7)
        assert isinstance(e, SanityError)
        assert e.exit_code == 7

    def test_zero_result_exit_code_maps_to_one(self):
        e = _action_error(0)
        assert e.exit_code == 1

    def test_forensics_kept(self):
        action = RunSubprocess(argv=("docker", "up"))
        result = ActionResult(exit_code=2, stderr="boom")
        e = ActionFailedError(action, result, phase="up.docker")
        assert e.action is action
        assert e.result is result
        assert e.phase == "up.docker"


class TestLifecyclePropagation:
    def test_down_propagates_action_failure(self):
        from sanity_gravity.verbs import lifecycle as lc

        args = argparse.Namespace(
            name="p", dry_run=False, reporter=_reporter(),
        )
        with patch.object(lc, "Orchestrator", _RaisingOrch), \
             patch.object(lc, "register_builtin_lifecycle_hooks",
                          lambda bus: None), \
             patch.object(lc, "build_default_executor",
                          lambda rep, dry_run=False: None):
            with pytest.raises(ActionFailedError) as ei:
                lc.down(args)
        assert ei.value.exit_code == 3


class TestSnapshotPropagation:
    def test_snapshot_propagates_action_failure(self):
        from sanity_gravity.verbs import snapshot as sn

        args = argparse.Namespace(
            name="p", tag="t:1", variant="ag-xfce-ssh",
            dry_run=False, reporter=_reporter(),
        )
        with patch.object(sn, "Orchestrator", _RaisingOrch), \
             patch.object(sn, "register_builtin_snapshot_hooks",
                          lambda bus: None), \
             patch.object(sn, "build_default_executor",
                          lambda rep, dry_run=False: None):
            with pytest.raises(ActionFailedError) as ei:
                sn.snapshot_cmd(args)
        assert ei.value.exit_code == 3


class TestUpAutoPullFailure:
    def test_up_raises_its_own_message_when_auto_pull_fails(
        self, tmp_path, monkeypatch, fake_proc,
    ):
        """Decision 2: pull() reports, up() decides -- the verb emits
        its own failure instead of pull exiting from underneath it."""
        from sanity_gravity.verbs import pull as pull_mod
        from sanity_gravity.verbs import up as up_mod

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            up_mod, "get_uid_gid_user", lambda: (1000, 1000, "dev"),
        )
        # Image missing -> auto-pull triggers. Nothing else may shell
        # out here: pull itself is stubbed below, so any other command
        # is unscripted and fails loudly.
        fake_proc.script("docker image inspect", rc=1)
        monkeypatch.setattr(
            pull_mod, "pull",
            lambda args: pull_mod.PullReport(
                succeeded=(), failed=("ag-xfce-kasm",),
            ),
        )

        args = argparse.Namespace(
            variant="ag-xfce-kasm", name="proj", skip_check=True,
            pull=False, dry_run=False, recreate=False, workspace=None,
            ssh_port="2222", kasm_port="8444", vnc_port="5901",
            novnc_port="6901", password="pw", cpus=None, memory=None,
            image=None, tag=None, reporter=_reporter(),
        )
        with pytest.raises(SanityError) as ei:
            up_mod.up(args)
        assert "ag-xfce-kasm" in str(ei.value)
        assert ei.value.exit_code == 1


class TestBuildPropagation:
    def test_build_propagates_action_failure(self):
        from sanity_gravity.verbs import build as build_mod

        args = argparse.Namespace(
            no_cache=False, list_intermediates=False,
            layer=None, layer_target=None, variant=["ag-xfce-kasm"],
            dry_run=False, json_output=False, reporter=_reporter(),
        )
        with patch.object(build_mod, "Orchestrator", _RaisingOrch), \
             patch.object(build_mod, "register_builtin_build_hooks",
                          lambda bus: None), \
             patch.object(build_mod, "build_default_executor",
                          lambda rep, dry_run=False: None):
            with pytest.raises(ActionFailedError) as ei:
                build_mod.build(args)
        assert ei.value.exit_code == 3

    def test_build_bad_tag_raises_tag_error(self):
        from sanity_gravity.domain.tags import TagError
        from sanity_gravity.verbs import build as build_mod

        args = argparse.Namespace(
            no_cache=False, list_intermediates=False,
            layer=None, layer_target=None, variant=["zz-zz-zz"],
            dry_run=False, json_output=False, reporter=_reporter(),
        )
        with pytest.raises(TagError):
            build_mod.build(args)


class TestUpPropagation:
    def _args(self, **kw):
        defaults = dict(
            variant="ag-xfce-kasm", name="proj", skip_check=True,
            pull=False, dry_run=False, recreate=False, workspace=None,
            ssh_port="2222", kasm_port="8444", vnc_port="5901",
            novnc_port="6901", password="pw", cpus=None, memory=None,
            image=None, reporter=_reporter(),
        )
        defaults.update(kw)
        return argparse.Namespace(**defaults)

    def test_up_bad_tag_raises_tag_error(self):
        from sanity_gravity.domain.tags import TagError
        from sanity_gravity.verbs import up as up_mod

        with pytest.raises(TagError):
            up_mod.up(self._args(variant="zz-zz-zz"))

    def test_up_collision_raises_sanity_error_with_hints(self, tmp_path,
                                                         monkeypatch,
                                                         fake_proc):
        from sanity_gravity.verbs import up as up_mod

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            up_mod, "get_uid_gid_user", lambda: (1000, 1000, "dev"),
        )
        # Image exists (no auto-pull); collision probe finds a container.
        fake_proc.script("docker image inspect", stdout='[{"Id":"x"}]')
        fake_proc.script("docker ps", stdout="abc123")

        with pytest.raises(SanityError) as ei:
            up_mod.up(self._args())
        assert "already exists" in str(ei.value)
        assert ei.value.exit_code == 1
        # The three recovery commands stay, now as the hint field.
        for phrase in ("sanity-cli start", "--recreate", "sanity-cli clean"):
            assert phrase in (ei.value.hint or "")

    def test_up_action_failure_reports_run_dir_and_propagates(
        self, tmp_path, monkeypatch, fake_proc,
    ):
        from sanity_gravity.verbs import up as up_mod

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            up_mod, "get_uid_gid_user", lambda: (1000, 1000, "dev"),
        )
        # Image exists, no collision: the pre-flight must wave the run
        # through so the failure under test comes from the kernel.
        fake_proc.script("docker image inspect", stdout='[{"Id":"x"}]')
        fake_proc.script("docker ps", stdout="")
        monkeypatch.setattr(up_mod, "Orchestrator", _RaisingOrch)
        monkeypatch.setattr(
            up_mod, "register_builtin_up_hooks", lambda bus: None,
        )
        monkeypatch.setattr(
            up_mod, "build_default_executor",
            lambda rep, dry_run=False: None,
        )

        infos: list[str] = []
        reporter = _reporter()
        reporter.info = infos.append  # type: ignore[method-assign]
        monkeypatch.setattr(up_mod, "get_reporter", lambda: reporter)

        with pytest.raises(ActionFailedError) as ei:
            up_mod.up(self._args(reporter=reporter))
        assert ei.value.exit_code == 3
        assert any("Detailed run state" in m for m in infos)

    def test_up_plain_valueerror_from_kernel_becomes_sanity_error(
        self, tmp_path, monkeypatch, fake_proc,
    ):
        """Deps validators still raise bare ValueError inside the phase
        run; the verb wraps it so the boundary renders it (exit 1, no
        traceback) exactly as the old print+exit did."""
        from sanity_gravity.verbs import up as up_mod

        class _ValueErrorOrch(_RaisingOrch):
            def run(self, phases, ctx):
                raise ValueError("Invalid project name 'x!'")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            up_mod, "get_uid_gid_user", lambda: (1000, 1000, "dev"),
        )
        fake_proc.script("docker image inspect", stdout='[{"Id":"x"}]')
        fake_proc.script("docker ps", stdout="")
        monkeypatch.setattr(up_mod, "Orchestrator", _ValueErrorOrch)
        monkeypatch.setattr(
            up_mod, "register_builtin_up_hooks", lambda bus: None,
        )
        monkeypatch.setattr(
            up_mod, "build_default_executor",
            lambda rep, dry_run=False: None,
        )

        with pytest.raises(SanityError) as ei:
            up_mod.up(self._args())
        assert not isinstance(ei.value, ValueError)  # wrapped, not raw
        assert "Invalid project name" in str(ei.value)
        assert ei.value.exit_code == 1
