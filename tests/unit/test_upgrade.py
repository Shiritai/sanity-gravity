"""Tests for ``verbs/upgrade.py`` — the lossless persistent-home migration.

The verb shells out to docker heavily; these tests mock ``run_step`` /
``run_command`` and the compose generators so the *ordering* and
*safety invariants* of the migration are exercised without a daemon.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest


from sanity_gravity.verbs import upgrade as up_mod


# ---------------------------------------------------------------------------
# run_step
# ---------------------------------------------------------------------------


class TestRunStep:
    def test_returns_stdout_on_success(self):
        fake = MagicMock(returncode=0, stdout="  hello\n", stderr="")
        with patch.object(up_mod.subprocess, "run", return_value=fake):
            assert up_mod.run_step(("docker", "ps"), capture=True) == "hello"

    def test_raises_runtimeerror_on_failure(self):
        fake = MagicMock(returncode=1, stdout="", stderr="boom\n")
        with patch.object(up_mod.subprocess, "run", return_value=fake):
            with pytest.raises(RuntimeError, match="boom"):
                up_mod.run_step(("docker", "commit", "x", "y"))

    def test_failure_never_calls_sys_exit(self):
        """run_step must raise, not sys.exit — a half-done migration has
        to be catchable so it can report its stage."""
        fake = MagicMock(returncode=2, stdout="", stderr="")
        with patch.object(up_mod.subprocess, "run", return_value=fake):
            with pytest.raises(RuntimeError):
                up_mod.run_step(("docker", "x"))
            # (pytest.raises catching SystemExit would also pass, so be
            # explicit: the raised type is RuntimeError, not SystemExit.)


# ---------------------------------------------------------------------------
# _recover_env
# ---------------------------------------------------------------------------


class TestRecoverEnv:
    def test_fills_host_defaults(self):
        with patch.object(up_mod, "get_project_env", return_value={}), \
             patch.object(up_mod, "get_published_ports", return_value={}), \
             patch.object(up_mod, "is_port_in_use", return_value=False):
            env = up_mod._recover_env("custom-proj", "cid", 1000, 1000, "alice")
        assert env["HOST_USER"] == "alice"
        assert env["HOST_UID"] == "1000"
        assert env["HOST_GID"] == "1000"

    def test_custom_project_zeros_all_ports(self):
        with patch.object(up_mod, "get_project_env", return_value={}), \
             patch.object(up_mod, "get_published_ports", return_value={}), \
             patch.object(up_mod, "is_port_in_use", return_value=False):
            env = up_mod._recover_env("myproj", "cid", 1000, 1000, "alice")
        assert env["SSH_HOST_PORT"] == "0"
        assert env["KASM_PORT"] == "0"
        assert env["VNC_PORT"] == "0"
        assert env["NOVNC_PORT"] == "0"

    def test_default_project_only_zeros_busy_ports(self):
        with patch.object(up_mod, "get_project_env", return_value={}), \
             patch.object(up_mod, "get_published_ports", return_value={}), \
             patch.object(up_mod, "is_port_in_use",
                          side_effect=lambda p: p == 8444):
            env = up_mod._recover_env("sanity-gravity", "cid", 1000, 1000, "alice")
        assert env["KASM_PORT"] == "0"          # 8444 busy
        assert "SSH_HOST_PORT" not in env       # 2222 free
        assert "VNC_PORT" not in env

    def test_preexisting_port_preserved(self):
        with patch.object(up_mod, "get_project_env",
                          return_value={"KASM_PORT": "55555"}), \
             patch.object(up_mod, "get_published_ports", return_value={}), \
             patch.object(up_mod, "is_port_in_use", return_value=True):
            env = up_mod._recover_env("sanity-gravity", "cid", 1000, 1000, "alice")
        assert env["KASM_PORT"] == "55555"      # not overwritten with 0

    def test_recovered_published_ports_pin_the_migrated_container(self):
        """A port the old container had bound to a fixed host port must
        carry over — not be replaced by an ephemeral 0."""
        with patch.object(up_mod, "get_project_env", return_value={}), \
             patch.object(up_mod, "get_published_ports",
                          return_value={"KASM_PORT": "33007"}), \
             patch.object(up_mod, "is_port_in_use", return_value=True):
            env = up_mod._recover_env("sanity-gravity", "oldcid", 1000, 1000, "alice")
        assert env["KASM_PORT"] == "33007"      # preserved from old binding

    def test_intentionally_ephemeral_port_stays_ephemeral(self):
        """PortBindings records a user-ephemeral port as "0"; that "0"
        must survive the second (fallback) pass unchanged."""
        with patch.object(up_mod, "get_project_env", return_value={}), \
             patch.object(up_mod, "get_published_ports",
                          return_value={"SSH_HOST_PORT": "0"}), \
             patch.object(up_mod, "is_port_in_use", return_value=False):
            env = up_mod._recover_env("sanity-gravity", "oldcid", 1000, 1000, "alice")
        assert env["SSH_HOST_PORT"] == "0"


class TestGetPublishedPorts:
    def test_maps_container_ports_to_env_vars(self):
        # Two bound ports; docker inspect emits "<cport>=<hostport> ..."
        out = "22/tcp=33001 8444/tcp=33007 "
        with patch.object(up_mod, "run_command", return_value=out):
            ports = up_mod.get_published_ports("cid")
        assert ports == {"SSH_HOST_PORT": "33001", "KASM_PORT": "33007"}

    def test_unbound_or_unknown_ports_ignored(self):
        # 9999/tcp is not a sanity connector port → dropped.
        out = "9999/tcp=40000 5901/tcp=33010"
        with patch.object(up_mod, "run_command", return_value=out):
            ports = up_mod.get_published_ports("cid")
        assert ports == {"VNC_PORT": "33010"}

    def test_empty_inspect_output_yields_empty(self):
        with patch.object(up_mod, "run_command", return_value=""):
            assert up_mod.get_published_ports("cid") == {}


# ---------------------------------------------------------------------------
# upgrade — planning
# ---------------------------------------------------------------------------


class TestUpgradePlanning:
    def test_nothing_to_migrate(self):
        with patch.object(up_mod, "get_legacy_containers", return_value=[]), \
             patch.object(up_mod, "print_success") as ok, \
             patch("sanity_gravity.verbs.status.status"):
            up_mod.upgrade(argparse.Namespace(name="sanity-gravity"))
        ok.assert_called_once()
        assert "Nothing to migrate" in ok.call_args[0][0]

    def test_unmappable_service_skipped(self):
        recs = [{"cid": "c1", "name": "x-web-1", "project": "x", "service": "web"}]
        with patch.object(up_mod, "get_legacy_containers", return_value=recs), \
             patch.object(up_mod, "print_warning") as warn, \
             patch.object(up_mod, "print_error") as err, \
             patch.object(up_mod, "print_header"), \
             patch("sanity_gravity.verbs.status.status"):
            up_mod.upgrade(argparse.Namespace(name="sanity-gravity"))
        # 'web' can't map to a tag → warned and then "Nothing migratable".
        assert any("cannot map service" in c[0][0] for c in warn.call_args_list)
        err.assert_called_once()
        assert "Nothing migratable" in err.call_args[0][0]

    def test_named_project_with_no_records(self):
        with patch.object(up_mod, "get_legacy_containers", return_value=[]), \
             patch.object(up_mod, "get_legacy_projects", return_value=[]), \
             patch.object(up_mod, "print_error") as err, \
             patch("sanity_gravity.verbs.status.status"):
            up_mod.upgrade(argparse.Namespace(name="missing-proj"))
        err.assert_called_once()
        assert "no container needing migration" in err.call_args[0][0]


# ---------------------------------------------------------------------------
# _migrate_one — the safety-critical ordering
# ---------------------------------------------------------------------------


def _docker_subcmd(argv):
    """Return a short label for a docker argv, for sequence assertions."""
    a = list(argv)
    if a[:2] == ["docker", "commit"]:
        return "commit"
    if a[:3] == ["docker", "rm", "-f"]:
        return "rm"
    if a[:2] == ["docker", "compose"] and "create" in a:
        return "create"
    if a[:2] == ["docker", "compose"] and "start" in a:
        return "start"
    if a[:2] == ["docker", "inspect"]:
        return "inspect"
    if a[:2] == ["docker", "run"]:
        return "seed"
    if a[:3] == ["docker", "ps", "-q"]:
        return "verify"
    return " ".join(a[:3])


class TestMigrateOneOrdering:
    def _item(self):
        return {
            "cid": "oldcid", "name": "proj-kasm-1",
            "project": "proj", "service": "kasm", "tag": "ag-xfce-kasm",
        }

    def test_snapshot_precedes_removal(self):
        """The container must be `docker commit`-ed BEFORE `docker rm -f`
        — losing data before the snapshot is the whole bug class this
        migration exists to prevent."""
        calls = []

        def fake_run_step(argv, *, capture=False, env=None):
            calls.append(_docker_subcmd(argv))
            if _docker_subcmd(argv) == "inspect":
                return "proj_sanity_home"
            if _docker_subcmd(argv) == "verify":
                return "newcid"          # container came up
            return ""

        with patch.object(up_mod, "run_step", side_effect=fake_run_step), \
             patch.object(up_mod, "get_project_env",
                          return_value={"HOST_USER": "alice"}), \
             patch.object(up_mod, "get_published_ports", return_value={}), \
             patch.object(up_mod, "is_port_in_use", return_value=False), \
             patch.object(up_mod, "generate_compose_for_tag",
                          return_value=("config/docker-compose.ag-xfce-kasm.yml", "ag-xfce-kasm")), \
             patch.object(up_mod, "generate_git_compose", return_value=None), \
             patch.object(up_mod, "print_header"), \
             patch.object(up_mod, "print_info"), \
             patch.object(up_mod, "print_success"):
            up_mod._migrate_one(self._item(), 1000, 1000, "alice", "20260518-000000")

        assert "commit" in calls and "rm" in calls
        assert calls.index("commit") < calls.index("rm"), calls
        # Full expected sequence.
        assert calls == ["commit", "rm", "create", "inspect", "seed",
                         "start", "verify"]

    def test_git_overlay_scoped_to_tag(self):
        """generate_git_compose must be called WITH the tag — omitting it
        emits image-less services for every VALID_TAG."""
        with patch.object(up_mod, "run_step",
                          side_effect=lambda a, **k: "proj_sanity_home"
                          if _docker_subcmd(a) == "inspect" else
                          ("newcid" if _docker_subcmd(a) == "verify" else "")), \
             patch.object(up_mod, "get_project_env",
                          return_value={"HOST_USER": "alice"}), \
             patch.object(up_mod, "get_published_ports", return_value={}), \
             patch.object(up_mod, "is_port_in_use", return_value=False), \
             patch.object(up_mod, "generate_compose_for_tag",
                          return_value=("config/c.yml", "ag-xfce-kasm")), \
             patch.object(up_mod, "generate_git_compose",
                          return_value=None) as gitgen, \
             patch.object(up_mod, "print_header"), \
             patch.object(up_mod, "print_info"), \
             patch.object(up_mod, "print_success"):
            up_mod._migrate_one(self._item(), 1000, 1000, "alice", "ts")
        gitgen.assert_called_once_with("alice", "ag-xfce-kasm")

    def test_failure_before_removal_carries_intact_stage(self):
        """If the snapshot step fails, the exception's .stage is
        'snapshot' so the caller can tell the user nothing was lost."""
        def fake_run_step(argv, *, capture=False, env=None):
            if _docker_subcmd(argv) == "commit":
                raise RuntimeError("disk full")
            return ""

        with patch.object(up_mod, "run_step", side_effect=fake_run_step), \
             patch.object(up_mod, "print_header"), \
             patch.object(up_mod, "print_info"):
            with pytest.raises(RuntimeError) as ei:
                up_mod._migrate_one(self._item(), 1000, 1000, "alice", "ts")
            assert ei.value.stage == "snapshot"

    def test_failure_after_removal_carries_removed_stage(self):
        """If a step after `rm` fails, .stage reflects that the old
        container is already gone (data still safe in the snapshot)."""
        def fake_run_step(argv, *, capture=False, env=None):
            sub = _docker_subcmd(argv)
            if sub == "create":
                raise RuntimeError("compose rejected")
            return ""

        with patch.object(up_mod, "run_step", side_effect=fake_run_step), \
             patch.object(up_mod, "get_project_env",
                          return_value={"HOST_USER": "alice"}), \
             patch.object(up_mod, "get_published_ports", return_value={}), \
             patch.object(up_mod, "is_port_in_use", return_value=False), \
             patch.object(up_mod, "generate_compose_for_tag",
                          return_value=("config/c.yml", "ag-xfce-kasm")), \
             patch.object(up_mod, "generate_git_compose", return_value=None), \
             patch.object(up_mod, "print_header"), \
             patch.object(up_mod, "print_info"):
            with pytest.raises(RuntimeError) as ei:
                up_mod._migrate_one(self._item(), 1000, 1000, "alice", "ts")
            assert ei.value.stage == "old-removed"
            assert "sanity-migrate/" in ei.value.backup_img
