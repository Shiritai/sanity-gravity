"""Tests for ``verbs/lifecycle.py`` discovery helpers.

The discovery helpers speak ``core.proc.capture``: stdout is the value,
``[]`` / ``{}`` mean only "nothing exists in the domain", and a docker
failure raises CommandError instead of collapsing into the same empty
value (the old warn-and-return-[] behaviour made "daemon down" and "no
projects" indistinguishable).

Each helper is pinned by the shape of the command it issues, so the
scripted stdout can only reach the helper that actually asked for it --
a stdout wired to the wrong ``docker ps`` would raise UnscriptedCommand
rather than quietly satisfy the assertion. rc=1 rules exercise the real
``capture`` contract: the fake raises CommandError exactly where the
production boundary does.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from sanity_gravity.domain.errors import CommandError

# Substrings that identify each helper's docker invocation.
MANAGED_PS = "label=sanity.gravity.managed=true"
PROJECT_PS = "label=com.docker.compose.project="
LEGACY_PS = "sanity.gravity.home-volume"
INSPECT_ENV = "docker inspect"


class TestGetManagedProjects:
    def test_returns_sorted_unique_projects(self, fake_proc):
        from sanity_gravity.verbs import lifecycle as lc

        fake_proc.script(MANAGED_PS, stdout="b\na\nb\n")
        assert lc.get_managed_projects() == ["a", "b"]

    def test_empty_output_returns_empty_list(self, fake_proc):
        """Ok("") is the legitimate domain answer: no projects."""
        from sanity_gravity.verbs import lifecycle as lc

        fake_proc.script(MANAGED_PS, stdout="")
        assert lc.get_managed_projects() == []

    def test_docker_failure_raises_command_error(self, fake_proc):
        """Err is no longer collapsed into the Ok-empty value."""
        from sanity_gravity.verbs import lifecycle as lc

        fake_proc.script(MANAGED_PS, rc=1, stderr="daemon down")
        with pytest.raises(CommandError):
            lc.get_managed_projects()


class TestFindProjectContainers:
    def test_docker_failure_raises_command_error(self, fake_proc):
        from sanity_gravity.verbs import lifecycle as lc

        fake_proc.script(PROJECT_PS + "p", rc=1, stderr="daemon down")
        with pytest.raises(CommandError):
            lc.find_project_containers("p")


class TestGetProjectEnv:
    """Discovery is stubbed out so these pin the env-parsing step alone."""

    def test_docker_failure_raises_command_error(self, fake_proc):
        from sanity_gravity.verbs import lifecycle as lc

        match = [{"cid": "c1", "name": "p-ag-xfce-kasm-1",
                  "service": "ag-xfce-kasm", "running": True}]
        fake_proc.script(INSPECT_ENV, rc=1, stderr="daemon down")
        with patch.object(lc, "find_project_containers", return_value=match):
            with pytest.raises(CommandError):
                lc.get_project_env("p")

    def test_no_matching_env_returns_empty_dict(self, fake_proc):
        """{} means only "the domain has no such env" -- the container
        answered, just without any recognized key."""
        from sanity_gravity.verbs import lifecycle as lc

        match = [{"cid": "c1", "name": "p-ag-xfce-kasm-1",
                  "service": "ag-xfce-kasm", "running": True}]
        fake_proc.script(INSPECT_ENV, stdout="OTHER=1\n")
        with patch.object(lc, "find_project_containers", return_value=match):
            assert lc.get_project_env("p") == {}

    def test_recognized_env_collected(self, fake_proc):
        from sanity_gravity.verbs import lifecycle as lc

        match = [{"cid": "c1", "name": "p-ag-xfce-kasm-1",
                  "service": "ag-xfce-kasm", "running": True}]
        out = "HOST_USER=alice\nSSH_HOST_PORT=2222\nNOISE=x\n"
        fake_proc.script(INSPECT_ENV, stdout=out)
        with patch.object(lc, "find_project_containers", return_value=match):
            assert lc.get_project_env("p") == {
                "HOST_USER": "alice", "SSH_HOST_PORT": "2222",
            }


class TestGetLegacyProjects:
    """Legacy = container with a recognised service label but no managed label."""

    # ``get_legacy_containers`` emits one line per container, six
    # pipe-separated fields:
    #   ID|Names|project|service|managed|home-volume
    # "Legacy" = ours (managed / known service) AND home-volume != true.

    def test_legacy_detects_unmigrated_managed_container(self, fake_proc):
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
        fake_proc.script(LEGACY_PS, stdout=out)
        assert lc.get_legacy_projects() == ["p-flat", "p-old"]

    def test_legacy_containers_records_shape(self, fake_proc):
        from sanity_gravity.verbs import lifecycle as lc

        out = "c1|p-old-svc-1|p-old|kasm||\n"
        fake_proc.script(LEGACY_PS, stdout=out)
        recs = lc.get_legacy_containers()
        assert recs == [
            {"cid": "c1", "name": "p-old-svc-1",
             "project": "p-old", "service": "kasm"},
        ]

    def test_legacy_empty_when_no_containers(self, fake_proc):
        from sanity_gravity.verbs import lifecycle as lc

        fake_proc.script(LEGACY_PS, stdout="")
        assert lc.get_legacy_projects() == []
        assert lc.get_legacy_containers() == []

    def test_legacy_all_migrated_returns_empty(self, fake_proc):
        from sanity_gravity.verbs import lifecycle as lc

        out = "c1|p-done-svc-1|p-done|ag-xfce-kasm|true|true\n"
        fake_proc.script(LEGACY_PS, stdout=out)
        assert lc.get_legacy_projects() == []

    def test_legacy_docker_failure_raises_command_error(self, fake_proc):
        from sanity_gravity.verbs import lifecycle as lc

        fake_proc.script(LEGACY_PS, rc=1, stderr="daemon down")
        with pytest.raises(CommandError):
            lc.get_legacy_containers()


class TestLegacyTargetTag:
    """``legacy_target_tag`` maps an old/managed service to its migration tag."""

    def test_flat_legacy_services_map_to_ag_xfce(self):
        from sanity_gravity.verbs.lifecycle import legacy_target_tag

        assert legacy_target_tag("core") == "ag-xfce-ssh"
        assert legacy_target_tag("kasm") == "ag-xfce-kasm"
        assert legacy_target_tag("vnc") == "ag-xfce-vnc"

    def test_already_tagged_service_migrates_in_place(self):
        from sanity_gravity.core.registry import VALID_TAGS
        from sanity_gravity.verbs.lifecycle import legacy_target_tag

        tag = VALID_TAGS[0]
        assert legacy_target_tag(tag) == tag

    def test_unknown_service_unmappable(self):
        from sanity_gravity.verbs.lifecycle import legacy_target_tag

        assert legacy_target_tag("web") is None
        assert legacy_target_tag("postgres") is None
