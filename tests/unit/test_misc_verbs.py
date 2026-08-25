"""Coverage for ``verbs/open.py``, ``verbs/shell.py`` and the
``verbs/sync.py`` interactive prompt path.
"""
from __future__ import annotations

import argparse
import subprocess
from unittest.mock import patch

import pytest

from tests.conftest import container_record


def _match(project, service):
    """One discovery record, shaped like find_project_containers returns."""
    return [container_record(service, project)]


# ---------------------------------------------------------------------------
# verbs/open.py
# ---------------------------------------------------------------------------


class TestOpenVerb:
    def test_no_active_projects(self):
        from sanity_gravity.verbs import open as open_mod

        with patch.object(open_mod, "get_active_projects", return_value=[]), \
             patch.object(open_mod, "print_error") as err:
            open_mod.open_cmd(argparse.Namespace(name="sanity-gravity"))
            err.assert_called_once()
            assert "No active projects" in err.call_args[0][0]

    def test_no_running_container(self):
        from sanity_gravity.verbs import open as open_mod

        with patch.object(open_mod, "get_active_projects",
                          return_value=["proj1"]), \
             patch.object(open_mod, "find_project_containers",
                          return_value=[]), \
             patch.object(open_mod, "print_error") as err:
            open_mod.open_cmd(argparse.Namespace(name="proj1"))
            err.assert_called_once()
            assert "No running containers" in err.call_args[0][0]

    def test_kasm_variant_opens_https_url(self, fake_proc):
        from sanity_gravity.verbs import open as open_mod

        # Scripted on the port probe's own shape: a kasm variant must ask
        # compose for the 8444 binding, not some other port.
        fake_proc.script("compose -p proj1 port ag-xfce-kasm 8444",
                         stdout="0.0.0.0:9999")

        with patch.object(open_mod, "get_active_projects",
                          return_value=["proj1"]), \
             patch.object(open_mod, "find_project_containers",
                          return_value=_match("proj1", "ag-xfce-kasm")), \
             patch.object(open_mod.webbrowser, "open") as wb, \
             patch.object(open_mod, "print_success"):
            open_mod.open_cmd(argparse.Namespace(name="proj1"))
            wb.assert_called_once()
            url = wb.call_args[0][0]
            assert url.startswith("https://localhost:")
            assert "9999" in url

    def test_port_probe_failure_warns_instead_of_silence(self, fake_proc):
        """docker compose failing is no longer indistinguishable from
        "no port bound": the rc drives an explicit warning (the old
        except-CalledProcessError arm was dead code -- check=False
        never raised)."""
        from sanity_gravity.verbs import open as open_mod

        fake_proc.script("compose -p proj1 port ag-xfce-kasm 8444",
                         rc=1, stderr="daemon down")

        with patch.object(open_mod, "get_active_projects",
                          return_value=["proj1"]), \
             patch.object(open_mod, "find_project_containers",
                          return_value=_match("proj1", "ag-xfce-kasm")), \
             patch.object(open_mod.webbrowser, "open") as wb, \
             patch.object(open_mod, "print_warning") as warn, \
             patch.object(open_mod, "print_error") as err:
            open_mod.open_cmd(argparse.Namespace(name="proj1"))
            wb.assert_not_called()
            warn.assert_called_once()
            assert "Could not resolve" in warn.call_args[0][0]
            err.assert_called_once()  # "Could not resolve accessible URL."

    def test_ssh_variant_warns_no_web(self):
        from sanity_gravity.verbs import open as open_mod

        with patch.object(open_mod, "get_active_projects",
                          return_value=["proj1"]), \
             patch.object(open_mod, "find_project_containers",
                          return_value=_match("proj1", "gc-none-ssh")), \
             patch.object(open_mod.webbrowser, "open") as wb, \
             patch.object(open_mod, "print_warning") as warn:
            open_mod.open_cmd(argparse.Namespace(name="proj1"))
            warn.assert_called_once()
            assert "no web interface" in warn.call_args[0][0]
            wb.assert_not_called()


# ---------------------------------------------------------------------------
# verbs/shell.py
# ---------------------------------------------------------------------------


class TestShellVerb:
    def _args(self, name="sanity-gravity"):
        return argparse.Namespace(name=name, user=None)

    def test_no_active_projects_is_nonzero(self):
        """Precondition failure must not be print_error + return: the
        dispatcher drops the return value, so that shape prints a red X
        and exits 0 - the lying-success family again."""
        from sanity_gravity.domain.errors import SanityError
        from sanity_gravity.verbs import shell as shell_mod

        with patch.object(shell_mod, "get_active_projects", return_value=[]):
            with pytest.raises(SanityError, match="No active projects"):
                shell_mod.shell_cmd(self._args())

    def test_no_running_container_is_nonzero(self):
        from sanity_gravity.domain.errors import SanityError
        from sanity_gravity.verbs import shell as shell_mod

        with patch.object(shell_mod, "get_active_projects",
                          return_value=["proj1"]), \
             patch.object(shell_mod, "find_project_containers",
                          return_value=[]):
            with pytest.raises(
                SanityError, match="No running containers found for proj1"
            ):
                shell_mod.shell_cmd(self._args(name="proj1"))

    def test_zsh_fallback_to_bash(self):
        """If zsh exec fails and ``--use`` was not given, fall back to
        bash via subprocess.call."""
        from sanity_gravity.verbs import shell as shell_mod

        with patch.object(shell_mod, "get_active_projects",
                          return_value=["proj1"]), \
             patch.object(shell_mod, "find_project_containers",
                          return_value=_match("proj1", "cc-none-ssh")), \
             patch.object(shell_mod, "get_project_env",
                          return_value={"HOST_USER": "alice"}), \
             patch.object(shell_mod, "print_info"), \
             patch.object(shell_mod, "print_warning") as warn, \
             patch.object(shell_mod.subprocess, "check_call",
                          side_effect=subprocess.CalledProcessError(1, "zsh")), \
             patch.object(shell_mod.subprocess, "call",
                          return_value=0) as fallback:
            shell_mod.shell_cmd(self._args(name="proj1"))
            fallback.assert_called_once()
            cmd = fallback.call_args[0][0]
            assert cmd[-1] == "bash"
            warn.assert_called_once()
            assert "falling back" in warn.call_args[0][0]

    def test_explicit_use_no_fallback_and_failure_is_nonzero(self):
        """When --use is set explicitly there is no bash fallback, and
        the failure must reach the boundary as a SanityError carrying
        the child's exit code - not a printed line and exit 0."""
        from sanity_gravity.domain.errors import SanityError
        from sanity_gravity.verbs import shell as shell_mod

        with patch.object(shell_mod, "get_active_projects",
                          return_value=["proj1"]), \
             patch.object(shell_mod, "find_project_containers",
                          return_value=_match("proj1", "cc-none-ssh")), \
             patch.object(shell_mod, "get_project_env",
                          return_value={"HOST_USER": "alice"}), \
             patch.object(shell_mod, "print_info"), \
             patch.object(shell_mod.subprocess, "check_call",
                          side_effect=subprocess.CalledProcessError(3, "fish")), \
             patch.object(shell_mod.subprocess, "call") as fallback:
            ns = argparse.Namespace(name="proj1", user=None, use="fish")
            with pytest.raises(SanityError) as ei:
                shell_mod.shell_cmd(ns)
            fallback.assert_not_called()
            assert ei.value.exit_code == 3
            assert "--use" in (str(ei.value) + (ei.value.hint or ""))

    def test_both_shells_failing_is_not_exit_zero(self):
        """The R-3 defect: zsh fails, bash fallback fails, and the rc of
        the bare subprocess.call was discarded - sanity-cli shell
        reported success. The fallback's rc now escalates."""
        from sanity_gravity.domain.errors import SanityError
        from sanity_gravity.verbs import shell as shell_mod

        with patch.object(shell_mod, "get_active_projects",
                          return_value=["proj1"]), \
             patch.object(shell_mod, "find_project_containers",
                          return_value=_match("proj1", "cc-none-ssh")), \
             patch.object(shell_mod, "get_project_env",
                          return_value={"HOST_USER": "alice"}), \
             patch.object(shell_mod, "print_info"), \
             patch.object(shell_mod, "print_warning"), \
             patch.object(shell_mod.subprocess, "check_call",
                          side_effect=subprocess.CalledProcessError(1, "zsh")), \
             patch.object(shell_mod.subprocess, "call",
                          return_value=127):
            with pytest.raises(SanityError) as ei:
                shell_mod.shell_cmd(self._args(name="proj1"))
            assert ei.value.exit_code == 127


# ---------------------------------------------------------------------------
# verbs/sync.py
# ---------------------------------------------------------------------------


class TestSyncVerbCmd:
    """Cover the wrapper / dispatch logic in ``sync_config_cmd``."""

    def test_no_active_projects_emits_info(self):
        from sanity_gravity.verbs import sync as sync_mod

        # ``sync_config_cmd`` lazily imports get_active_projects from
        # the lifecycle module — patch there so the late import sees
        # our stub.
        with patch("sanity_gravity.verbs.lifecycle.get_active_projects",
                   return_value=[]), \
             patch("sanity_gravity.verbs.lifecycle.get_project_env",
                   return_value={}), \
             patch.object(sync_mod, "print_info") as info, \
             patch.object(sync_mod, "print_warning"), \
             patch.object(sync_mod, "print_error"):
            sync_mod.sync_config_cmd(argparse.Namespace(name="sanity-gravity"))
            info.assert_called()
            joined = " ".join(c.args[0] for c in info.call_args_list)
            assert "No active" in joined or "no active" in joined.lower()

    def test_per_project_failure_fails_the_verb(self):
        """A project failing to sync must not end in 'Sync complete.' +
        exit 0: the remaining projects are still attempted, then the
        verb raises with the failed names."""
        from sanity_gravity.domain.errors import CommandError, SanityError
        from sanity_gravity.verbs import sync as sync_mod

        synced: list[str] = []

        def _sync(project, container, username):
            if project == "bad":
                raise CommandError(("docker", "exec"), 1, stderr="gone")
            synced.append(project)

        with patch("sanity_gravity.verbs.lifecycle.get_active_projects",
                   return_value=["bad", "good"]), \
             patch("sanity_gravity.verbs.lifecycle.get_project_env",
                   return_value={}), \
             patch("sanity_gravity.verbs.lifecycle.find_project_containers",
                   side_effect=lambda p: [{"name": f"{p}-c-1"}]), \
             patch.object(sync_mod, "sync_config", side_effect=_sync), \
             patch.object(sync_mod, "get_uid_gid_user",
                          return_value=(1000, 1000, "u")), \
             patch.object(sync_mod, "print_error") as err, \
             patch.object(sync_mod, "print_header"), \
             patch.object(sync_mod, "print_info"), \
             patch.object(sync_mod, "print_success") as ok:
            with pytest.raises(SanityError) as ei:
                sync_mod.sync_config_cmd(
                    argparse.Namespace(name="sanity-gravity"),
                )
        assert synced == ["good"]  # the failure did not abort the batch
        assert "bad" in str(ei.value)
        err.assert_called()  # per-project report still emitted
        ok.assert_not_called()  # no bogus "Sync complete."
