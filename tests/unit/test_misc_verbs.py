"""Coverage for ``verbs/open.py``, ``verbs/shell.py`` and the
``verbs/sync.py`` interactive prompt path.
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
             patch.object(open_mod, "run_command", return_value="false"), \
             patch.object(open_mod, "print_error") as err:
            open_mod.open_cmd(argparse.Namespace(name="proj1"))
            err.assert_called_once()
            assert "No running containers" in err.call_args[0][0]

    def test_kasm_variant_opens_https_url(self):
        from sanity_gravity.verbs import open as open_mod

        # First inspect call: variant is running. Second: resolve_port
        # returns ``0.0.0.0:9999``.
        outputs = iter(["true", "0.0.0.0:9999"])

        def fake_run(cmd, **_kw):
            return next(outputs)

        with patch.object(open_mod, "get_active_projects",
                          return_value=["proj1"]), \
             patch.object(open_mod, "run_command", side_effect=fake_run), \
             patch.object(open_mod, "parse_tag",
                          return_value=("ubuntu", "ag", "xfce", "kasm")), \
             patch.object(open_mod.webbrowser, "open") as wb, \
             patch.object(open_mod, "print_success"):
            open_mod.open_cmd(argparse.Namespace(name="proj1"))
            wb.assert_called_once()
            url = wb.call_args[0][0]
            assert url.startswith("https://localhost:")
            assert "9999" in url

    def test_ssh_variant_warns_no_web(self):
        from sanity_gravity.verbs import open as open_mod

        with patch.object(open_mod, "get_active_projects",
                          return_value=["proj1"]), \
             patch.object(open_mod, "run_command", return_value="true"), \
             patch.object(open_mod, "parse_tag",
                          return_value=("ubuntu", "gc", "none", "ssh")), \
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

    def test_no_active_projects(self):
        from sanity_gravity.verbs import shell as shell_mod

        with patch.object(shell_mod, "get_active_projects", return_value=[]), \
             patch.object(shell_mod, "print_error") as err:
            shell_mod.shell_cmd(self._args())
            err.assert_called_once()

    def test_no_running_container(self):
        from sanity_gravity.verbs import shell as shell_mod

        with patch.object(shell_mod, "get_active_projects",
                          return_value=["proj1"]), \
             patch.object(shell_mod, "run_command", return_value="false"), \
             patch.object(shell_mod, "print_error") as err:
            shell_mod.shell_cmd(self._args(name="proj1"))
            err.assert_called_once()
            assert "No running containers" in err.call_args[0][0]

    def test_zsh_fallback_to_bash(self):
        """If zsh exec fails and ``--use`` was not given, fall back to
        bash via subprocess.call."""
        from sanity_gravity.verbs import shell as shell_mod

        with patch.object(shell_mod, "get_active_projects",
                          return_value=["proj1"]), \
             patch.object(shell_mod, "run_command", return_value="true"), \
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

    def test_explicit_use_no_fallback(self):
        """When --use is set explicitly, no bash fallback even if it fails."""
        from sanity_gravity.verbs import shell as shell_mod

        with patch.object(shell_mod, "get_active_projects",
                          return_value=["proj1"]), \
             patch.object(shell_mod, "run_command", return_value="true"), \
             patch.object(shell_mod, "get_project_env",
                          return_value={"HOST_USER": "alice"}), \
             patch.object(shell_mod, "print_info"), \
             patch.object(shell_mod, "print_error") as err, \
             patch.object(shell_mod.subprocess, "check_call",
                          side_effect=subprocess.CalledProcessError(1, "fish")), \
             patch.object(shell_mod.subprocess, "call") as fallback:
            ns = argparse.Namespace(name="proj1", user=None, use="fish")
            shell_mod.shell_cmd(ns)
            fallback.assert_not_called()
            err.assert_called_once()


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
