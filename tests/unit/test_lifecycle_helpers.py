"""Tests for ``verbs/lifecycle.py`` discovery helpers.

``get_managed_projects`` and ``get_legacy_projects`` shell out to
``docker ps``; on failure they should warn and degrade to an empty list,
not crash the verb that called them.
"""
from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest


class TestGetManagedProjects:
    def test_returns_sorted_unique_projects(self):
        from sanity_gravity.verbs import lifecycle as lc

        with patch.object(lc, "run_command", return_value="b\na\nb\n"):
            assert lc.get_managed_projects() == ["a", "b"]

    def test_empty_output_returns_empty_list(self):
        from sanity_gravity.verbs import lifecycle as lc

        with patch.object(lc, "run_command", return_value=""):
            assert lc.get_managed_projects() == []

    def test_subprocess_error_warns_and_returns_empty(self):
        from sanity_gravity.verbs import lifecycle as lc

        with patch.object(lc, "run_command",
                          side_effect=subprocess.CalledProcessError(1, "docker ps")), \
             patch.object(lc, "print_warning") as warn:
            assert lc.get_managed_projects() == []
            warn.assert_called_once()
            assert "managed projects" in warn.call_args[0][0]

    def test_systemexit_from_run_command_warned_not_propagated(self):
        from sanity_gravity.verbs import lifecycle as lc

        with patch.object(lc, "run_command", side_effect=SystemExit(2)), \
             patch.object(lc, "print_warning") as warn:
            assert lc.get_managed_projects() == []
            warn.assert_called_once()


class TestGetLegacyProjects:
    """Legacy = container with a recognised service label but no managed label."""

    # ``get_legacy_containers`` emits one line per container, six
    # pipe-separated fields:
    #   ID|Names|project|service|managed|home-volume
    # "Legacy" = ours (managed / known service) AND home-volume != true.

    def test_legacy_detects_unmigrated_managed_container(self):
        from sanity_gravity.verbs import lifecycle as lc

        out = (
            # managed but no home volume → needs migration
            "c1|p-old-svc-1|p-old|ag-xfce-kasm|true|\n"
            # flat legacy service, no labels → needs migration
            "c2|p-flat-kasm-1|p-flat|kasm||\n"
            # already migrated (home-volume=true) → skip
            "c3|p-done-svc-1|p-done|ag-none-ssh|true|true\n"
            # not ours at all → skip
            "c4|other-web-1|other|web||\n"
        )
        with patch.object(lc, "run_command", return_value=out):
            assert lc.get_legacy_projects() == ["p-flat", "p-old"]

    def test_legacy_containers_records_shape(self):
        from sanity_gravity.verbs import lifecycle as lc

        out = "c1|p-old-svc-1|p-old|kasm||\n"
        with patch.object(lc, "run_command", return_value=out):
            recs = lc.get_legacy_containers()
        assert recs == [
            {"cid": "c1", "name": "p-old-svc-1",
             "project": "p-old", "service": "kasm"},
        ]

    def test_legacy_empty_when_no_containers(self):
        from sanity_gravity.verbs import lifecycle as lc

        with patch.object(lc, "run_command", return_value=""):
            assert lc.get_legacy_projects() == []
            assert lc.get_legacy_containers() == []

    def test_legacy_all_migrated_returns_empty(self):
        from sanity_gravity.verbs import lifecycle as lc

        out = "c1|p-done-svc-1|p-done|ag-xfce-kasm|true|true\n"
        with patch.object(lc, "run_command", return_value=out):
            assert lc.get_legacy_projects() == []

    def test_legacy_subprocess_error_warns(self):
        from sanity_gravity.verbs import lifecycle as lc

        with patch.object(lc, "run_command",
                          side_effect=subprocess.CalledProcessError(1, "docker ps")), \
             patch.object(lc, "print_warning") as warn:
            assert lc.get_legacy_containers() == []
            warn.assert_called_once()
            assert "legacy containers" in warn.call_args[0][0]


class TestLegacyTargetTag:
    """``legacy_target_tag`` maps an old/managed service to its migration tag."""

    def test_flat_legacy_services_map_to_ag_xfce(self):
        from sanity_gravity.verbs.lifecycle import legacy_target_tag

        assert legacy_target_tag("core") == "ag-xfce-ssh"
        assert legacy_target_tag("kasm") == "ag-xfce-kasm"
        assert legacy_target_tag("vnc") == "ag-xfce-vnc"

    def test_already_tagged_service_migrates_in_place(self):
        from sanity_gravity.verbs.lifecycle import legacy_target_tag
        from sanity_gravity.cli.registry import VALID_TAGS

        tag = VALID_TAGS[0]
        assert legacy_target_tag(tag) == tag

    def test_unknown_service_unmappable(self):
        from sanity_gravity.verbs.lifecycle import legacy_target_tag

        assert legacy_target_tag("web") is None
        assert legacy_target_tag("postgres") is None
