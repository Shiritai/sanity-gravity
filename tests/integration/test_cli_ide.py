"""Unit-style tests for the ``ide`` verb (no real Docker calls).

The patches target ``sanity_gravity.verbs.ide.{find_project_containers,get_active_projects}``
because that is where those names are looked up by ``ide_cmd``.
"""
from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from sanity_gravity.domain.errors import SanityError
from sanity_gravity.verbs import ide as ide_verb
from tests.conftest import container_record

pytestmark = pytest.mark.no_image

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


_REPO = str(_REPO_ROOT)


def _expected_calls(cname: str, subcommand: str):
    cli_src = os.path.join(
        _REPO, "plugins", "agents", "ag", "rootfs", "usr", "local", "bin", "gravity-cli"
    )
    cleanup_src = os.path.join(
        _REPO, "plugins", "agents", "ag", "rootfs", "usr", "local", "bin", "chrome-cleanup.sh"
    )
    conf_src = os.path.join(
        _REPO, "plugins", "agents", "ag", "rootfs", "usr", "local", "etc", "antigravity.conf"
    )
    devnull = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    return [
        ((("docker", "cp", cli_src, f"{cname}:/usr/local/bin/gravity-cli"),), devnull),
        ((("docker", "cp", cleanup_src, f"{cname}:/usr/local/bin/chrome-cleanup.sh"),), devnull),
        ((("docker", "cp", conf_src, f"{cname}:/usr/local/etc/antigravity.conf"),), devnull),
        ((("docker", "exec", "-u", "root", cname,
           "chmod", "+x", "/usr/local/bin/gravity-cli", "/usr/local/bin/chrome-cleanup.sh",
           "/usr/local/etc/antigravity.conf"),), devnull),
        ((("docker", "exec", "-it", "-u", "root", cname,
           "/usr/local/bin/gravity-cli", "ide", subcommand),), {}),
    ]


class TestIdeCommand:
    @patch("sanity_gravity.verbs.ide.find_project_containers")
    @patch("subprocess.check_call")
    @patch("sanity_gravity.verbs.ide.get_active_projects")
    def test_ide_update_success(self, mock_get_active, mock_check_call, mock_find):
        mock_get_active.return_value = ["sanity-gravity"]
        mock_find.return_value = [container_record("ag-xfce-kasm")]

        args = argparse.Namespace(name="sanity-gravity", ide_command="update")
        ide_verb.ide_cmd(args)

        cname = "sanity-gravity-ag-xfce-kasm-1"
        assert mock_check_call.call_args_list == _expected_calls(cname, "update")

    @patch("sanity_gravity.verbs.ide.find_project_containers")
    @patch("subprocess.check_call")
    @patch("sanity_gravity.verbs.ide.get_active_projects")
    def test_ide_reinstall_success(self, mock_get_active, mock_check_call, mock_find):
        mock_get_active.return_value = ["my-project"]
        mock_find.return_value = [
            container_record("ag-xfce-kasm", "my-project")
        ]

        args = argparse.Namespace(name="my-project", ide_command="reinstall")
        ide_verb.ide_cmd(args)

        cname = "my-project-ag-xfce-kasm-1"
        assert mock_check_call.call_args_list == _expected_calls(cname, "reinstall")

    @patch("sanity_gravity.verbs.ide.get_active_projects")
    def test_ide_container_not_found(self, mock_get_active):
        mock_get_active.return_value = ["other-project"]

        args = argparse.Namespace(
            name="non-existent-project", ide_command="update"
        )
        with pytest.raises(SanityError, match="is not active or managed"):
            ide_verb.ide_cmd(args)
