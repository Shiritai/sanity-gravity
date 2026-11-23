"""Tests for ``verbs/status.py`` — focused on the under-covered edges:
unknown project, daemon failure, empty active list.
"""
from __future__ import annotations

import argparse
from unittest.mock import patch

import pytest

from sanity_gravity.domain.errors import CommandError, SanityError


class TestStatusEdges:
    def test_no_active_projects_prints_info(self):
        from sanity_gravity.verbs import status as status_mod

        with patch.object(status_mod, "get_active_projects", return_value=[]), \
             patch.object(status_mod, "get_legacy_projects", return_value=[]), \
             patch.object(status_mod, "print_info") as info, \
             patch.object(status_mod, "print_warning") as warn, \
             patch.object(status_mod, "print_header"), \
             patch.object(status_mod, "print_error"):
            status_mod.status(argparse.Namespace(name="sanity-gravity"))
        info.assert_called_once()
        assert "No managed Sanity-Gravity instances" in info.call_args[0][0]
        warn.assert_not_called()

    def test_unknown_named_project_warns_then_continues(self):
        """Asking for an unmanaged project warns but doesn't crash —
        the verb still tries to ``docker compose ps`` for it."""
        from sanity_gravity.verbs import status as status_mod

        with patch.object(status_mod, "get_active_projects",
                          return_value=["other"]), \
             patch.object(status_mod, "get_legacy_projects", return_value=[]), \
             patch.object(status_mod, "capture", return_value=""), \
             patch.object(status_mod, "print_warning") as warn, \
             patch.object(status_mod, "print_info"), \
             patch.object(status_mod, "print_header"), \
             patch.object(status_mod, "print_error") as err:
            status_mod.status(argparse.Namespace(name="missing"))
        warn.assert_called_once()
        assert "not found in active projects" in warn.call_args[0][0]
        err.assert_not_called()

    def test_docker_compose_failure_reports_per_project(self):
        """A daemon failure is reported per project, the other projects
        are still shown, and the verb then exits non-zero."""
        from sanity_gravity.verbs import status as status_mod

        def ps(cmd, **_kw):
            if "proj1" in cmd:
                raise CommandError(tuple(cmd), 1, stderr="daemon down")
            return "proj2-row"

        with patch.object(status_mod, "get_active_projects",
                          return_value=["proj1", "proj2"]), \
             patch.object(status_mod, "get_legacy_projects", return_value=[]), \
             patch.object(status_mod, "capture", side_effect=ps), \
             patch.object(status_mod, "print_error") as err, \
             patch.object(status_mod, "print_plain") as plain, \
             patch.object(status_mod, "print_info"), \
             patch.object(status_mod, "print_header"), \
             patch.object(status_mod, "print_warning"), \
             pytest.raises(SanityError, match="1 of 2 project.*proj1"):
            status_mod.status(argparse.Namespace(name="sanity-gravity"))
        err.assert_called_once()
        assert "Failed to get status" in err.call_args[0][0]
        plain.assert_any_call("proj2-row")

    def test_legacy_warning_emitted_when_legacy_present(self, capsys):
        from sanity_gravity.verbs import status as status_mod

        with patch.object(status_mod, "get_active_projects", return_value=[]), \
             patch.object(status_mod, "get_legacy_projects",
                          return_value=["old-proj"]), \
             patch.object(status_mod, "print_info"), \
             patch.object(status_mod, "print_warning"), \
             patch.object(status_mod, "print_header"), \
             patch.object(status_mod, "print_error"):
            status_mod.status(argparse.Namespace(name="sanity-gravity"))
        out = capsys.readouterr().out
        assert "old-proj" in out
        assert "sanity-cli upgrade" in out
