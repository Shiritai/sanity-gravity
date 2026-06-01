"""CLI-level unit tests for sanity-cli verbs and registry projections.

The tests exercise the new :mod:`sanity_gravity` package directly. Patch
targets follow the standard ``mock.patch`` rule: patch the name where it
is *looked up*, not where it is defined. So ``run_command`` is patched
on the verb module that imports it (e.g.
``sanity_gravity.verbs.lifecycle.run_command``), not on
``sanity_gravity.cli.io`` where it lives.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from sanity_gravity.cli import registry as cli_registry  # noqa: E402
from sanity_gravity.cli.registry import (  # noqa: E402
    AGENTS,
    CONNECTORS,
    DESKTOPS,
    VALID_TAGS,
    parse_tag,
)
from sanity_gravity.verbs import lifecycle as lifecycle_mod  # noqa: E402
from sanity_gravity.verbs import open as open_mod  # noqa: E402
from sanity_gravity.verbs import shell as shell_mod  # noqa: E402
from sanity_gravity.verbs import snapshot as snapshot_mod  # noqa: E402
from sanity_gravity.verbs import sync as sync_mod  # noqa: E402
from sanity_gravity.verbs import up as up_mod  # noqa: E402
from sanity_gravity.verbs.build import (  # noqa: E402
    generate_intermediates,
    resolve_build_chain,
    resolve_parent,
)


class TestDimensionConstraints:
    """Tests for dimension-based tag constraint filtering."""

    def test_valid_tags_count(self):
        """At least 11 valid combinations."""
        assert len(VALID_TAGS) >= 11

    def test_bs_agent_removed(self):
        """bs (base) agent should not exist."""
        assert "bs" not in AGENTS

    def test_ag_requires_gui_desktop(self):
        """ag (antigravity) must have a GUI desktop."""
        with pytest.raises(ValueError, match="requires a GUI desktop"):
            parse_tag("ag-none-ssh")

    def test_gui_connector_requires_gui_desktop(self):
        """kasm/vnc connectors must have a GUI desktop."""
        for connector in ["kasm", "vnc"]:
            with pytest.raises(ValueError, match="requires a GUI desktop"):
                parse_tag(f"gc-none-{connector}")

    def test_headless_cli_agents_valid(self):
        """gc and cc can run headless with SSH."""
        for agent in ["gc", "cc"]:
            a, d, c = parse_tag(f"{agent}-none-ssh")
            assert a == agent
            assert d == "none"
            assert c == "ssh"

    def test_all_ag_tags_have_xfce(self):
        """Every ag tag must use xfce desktop."""
        ag_tags = [t for t in VALID_TAGS if t.startswith("ag-")]
        assert len(ag_tags) == 3
        for tag in ag_tags:
            assert "-xfce-" in tag

    def test_no_headless_gui_connector_in_valid_tags(self):
        """No *-none-kasm/vnc should appear in VALID_TAGS."""
        for tag in VALID_TAGS:
            _, desktop, connector = tag.split("-")
            if desktop == "none":
                assert connector == "ssh", f"Invalid combo in VALID_TAGS: {tag}"

    def test_registry_attributes(self):
        """Registries should have correct attribute structure."""
        for slug, info in AGENTS.items():
            assert "name" in info
            assert "requires_gui" in info
        for slug, info in CONNECTORS.items():
            assert "name" in info
            assert "requires_gui" in info
        for slug, info in DESKTOPS.items():
            assert "name" in info
            assert "has_gui" in info

    def test_unknown_agent_rejected(self):
        with pytest.raises(ValueError, match="Unknown agent"):
            parse_tag("bs-xfce-ssh")

    def test_invalid_format_rejected(self):
        with pytest.raises(ValueError, match="Invalid tag format"):
            parse_tag("ag-xfce")
        with pytest.raises(ValueError, match="Invalid tag format"):
            parse_tag("ag-xfce-kasm-extra")


class TestLayeredBuildSystem:
    """Tests for FROM-chained layered build system."""

    def test_resolve_build_chain_length(self):
        """Build chain always has 4 steps: base -> desktop -> agent -> connector."""
        chain = resolve_build_chain("ag-xfce-kasm")
        assert len(chain) == 4

    def test_resolve_build_chain_names(self):
        chain = resolve_build_chain("gc-none-ssh")
        names = [step[1] for step in chain]
        assert names == ["_base", "_base-none", "_gc-none", "gc-none-ssh"]

    def test_resolve_build_chain_parents(self):
        chain = resolve_build_chain("ag-xfce-vnc")
        parents = [step[2] for step in chain]
        assert parents == [None, "_base", "_base-xfce", "_ag-xfce"]

    def test_resolve_parent(self):
        assert resolve_parent("ag-xfce-kasm") == "_ag-xfce"
        assert resolve_parent("gc-none-ssh") == "_gc-none"
        assert resolve_parent("cc-xfce-vnc") == "_cc-xfce"

    def test_generate_intermediates(self):
        intermediates = generate_intermediates()
        assert "_base" in intermediates
        assert "_base-xfce" in intermediates
        assert "_base-none" in intermediates
        assert "_ag-xfce" in intermediates
        assert "_gc-none" in intermediates
        assert "_cc-xfce" in intermediates
        for name in intermediates:
            assert name.startswith("_"), f"Non-intermediate in list: {name}"

    def test_intermediates_count(self):
        """At least 8 intermediates."""
        assert len(generate_intermediates()) >= 8

    def test_shared_intermediates(self):
        """ag-xfce-kasm and ag-xfce-vnc share the same parent."""
        assert resolve_parent("ag-xfce-kasm") == resolve_parent("ag-xfce-vnc")

    def test_build_chain_dockerfiles_exist(self):
        """All Dockerfiles referenced in build chains must exist."""
        for tag in VALID_TAGS:
            chain = resolve_build_chain(tag)
            for dockerfile, _, _ in chain:
                assert os.path.exists(dockerfile), \
                    f"Missing: {dockerfile} (for {tag})"

    def test_layer_dockerfiles_have_from(self):
        """All non-base plugin Dockerfiles must have ARG BASE_IMAGE and FROM."""
        import glob
        plugin_dir = str(_REPO_ROOT / "plugins")
        for df in glob.glob(
            os.path.join(plugin_dir, "**", "Dockerfile"), recursive=True
        ):
            content = open(df).read()
            assert "ARG BASE_IMAGE" in content, f"Missing ARG BASE_IMAGE in {df}"
            assert "FROM ${BASE_IMAGE}" in content, f"Missing FROM in {df}"

    def test_rd_connector_removed(self):
        """rd connector should not exist."""
        assert "rd" not in CONNECTORS
        rd_dir = _REPO_ROOT / "plugins" / "connectors" / "rd"
        assert not rd_dir.exists()


class TestStatusDiscovery:
    """Tests for get_active_projects function."""

    @patch("sanity_gravity.verbs.lifecycle.run_command")
    def test_get_active_projects_discovery(self, mock_run):
        mock_output = """project-a
project-b
project-c"""
        mock_run.return_value = mock_output

        projects = lifecycle_mod.get_active_projects()

        assert "project-a" in projects
        assert "project-b" in projects
        assert "project-c" in projects
        assert len(projects) == 3

    @patch("sanity_gravity.verbs.lifecycle.run_command")
    def test_get_active_projects_empty(self, mock_run):
        mock_run.return_value = ""
        projects = lifecycle_mod.get_active_projects()
        assert projects == []

    @patch("sanity_gravity.verbs.lifecycle.run_command")
    def test_get_active_projects_error(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "docker ps")
        projects = lifecycle_mod.get_active_projects()
        assert projects == []


class TestConfigSync:
    """Tests for sync_config function."""

    @pytest.fixture
    def mock_env(self):
        with patch("os.path.exists") as mock_exists, \
             patch("os.makedirs") as mock_makedirs, \
             patch("shutil.copy2") as mock_copy, \
             patch("sanity_gravity.verbs.sync.run_command") as mock_run, \
             patch("builtins.print") as mock_print:
            yield mock_exists, mock_makedirs, mock_copy, mock_run, mock_print

    def test_sync_config_non_interactive(self, mock_env):
        mock_exists, _, _, mock_run, _ = mock_env

        mock_exists.side_effect = lambda p: p != "config"

        with patch("sys.stdin.isatty", return_value=False):
            sync_mod.sync_config("test-proj", "test-container", "user")

            for call_args in mock_run.call_args_list:
                cmd = call_args[0][0]
                cmd_str = (
                    " ".join(cmd) if isinstance(cmd, (list, tuple)) else cmd
                )
                assert "docker cp" not in cmd_str

    def test_sync_config_interactive_copy(self, mock_env):
        mock_exists, mock_makedirs, mock_copy, mock_run, _ = mock_env

        def exists_side_effect(path):
            if path == "config":
                return False
            if "GEMINI.md" in path:
                return True
            if "settings.json" in path:
                return True
            return False
        mock_exists.side_effect = exists_side_effect

        with patch("sys.stdin.isatty", return_value=True), \
             patch("builtins.input", return_value="a"):

            sync_mod.sync_config("test-proj", "test-container", "user")

            assert mock_copy.call_count >= 2

    def test_sync_config_interactive_flow(self):
        fs_state = {"config": False, "home_gemini": True}

        def exists_mock(path):
            if path == "config":
                return fs_state["config"]
            if ".gemini" in path:
                return True
            return False

        def makedirs_mock(path, exist_ok=True):
            if path == "config":
                fs_state["config"] = True

        with patch("os.path.exists", side_effect=exists_mock), \
             patch("os.makedirs", side_effect=makedirs_mock), \
             patch("shutil.copy2") as mock_copy, \
             patch("sanity_gravity.verbs.sync.run_command") as mock_run, \
             patch("sys.stdin.isatty", return_value=True), \
             patch("builtins.input", return_value="a"), \
             patch("builtins.print"):

            sync_mod.sync_config("test-proj", "test-container", "user")

            assert mock_copy.call_count >= 2

            def _as_str(cmd):
                return " ".join(cmd) if isinstance(cmd, (list, tuple)) else cmd
            docker_cmds = [
                _as_str(args[0][0]) for args in mock_run.call_args_list
            ]
            assert any("tar -cf -" in cmd for cmd in docker_cmds)
            assert any(
                "docker exec -i 'test-container' tar -xf -" in cmd
                or "docker exec -i test-container tar -xf -" in cmd
                for cmd in docker_cmds
            )

    def test_sync_config_safe_simulation(self):
        """Test sync_config with a custom source directory (simulation)."""
        import tempfile

        with tempfile.TemporaryDirectory() as temp_config_dir:
            gemini_path = os.path.join(temp_config_dir, "GEMINI.md")
            with open(gemini_path, "w") as f:
                f.write("# Safe Simulation Test")

            with patch("sanity_gravity.verbs.sync.run_command") as mock_run, \
                 patch("builtins.print"):

                sync_mod.sync_config(
                    "safe-proj", "safe-container", "user",
                    config_source=temp_config_dir,
                )

                def _as_str(cmd):
                    return (
                        " ".join(cmd)
                        if isinstance(cmd, (list, tuple)) else cmd
                    )
                docker_cmds = [
                    _as_str(args[0][0]) for args in mock_run.call_args_list
                ]

                import shlex as _shlex
                expected_tar_part = (
                    f"tar -cf - -C {_shlex.quote(temp_config_dir)}"
                )

                tar_commands = [
                    cmd for cmd in docker_cmds if "tar -cf -" in cmd
                ]

                assert len(tar_commands) > 0, "No tar sync command found"
                assert any(expected_tar_part in cmd for cmd in tar_commands)

                assert any(
                    "mkdir -p /home/user/.gemini" in cmd for cmd in docker_cmds
                )
                assert any(
                    "chown -R user:user /home/user/.gemini" in cmd
                    for cmd in docker_cmds
                )


class TestRunResourceArgs:
    """Tests for resource quota arguments."""

    @patch("sanity_gravity.verbs.up.run_command")
    @patch("sanity_gravity.verbs.up.get_uid_gid_user", return_value=(1000, 1000, "dev"))
    @patch("sanity_gravity.verbs.up.generate_resource_compose")
    @patch("sanity_gravity.compose.generators.ProxyManager")
    def test_run_with_resources(self, mock_pm, mock_gen_res, mock_user, mock_run):
        mock_instance = mock_pm.return_value
        mock_instance.is_enabled.return_value = False
        mock_gen_res.return_value = "config/docker-compose.resources.yml"

        from sanity_gravity.core.reporter import Reporter
        args = argparse.Namespace(
            variant="ag-xfce-ssh",
            cpus="1.5",
            memory="2G",
            skip_check=True,
            ssh_port="2222",
            kasm_port="8444",
            vnc_port="5901",
            novnc_port="6901",
            workspace=None,
            name="sanity-gravity",
            password="pass",
            image=None,
            dry_run=True,
            reporter=Reporter(sinks=[], run_id="t"),
        )

        from sanity_gravity.effects.executor import Executor as _Exec
        captured_actions = []
        orig_drain = _Exec.drain

        def _capture(self, actions, *, phase=None):
            for a in actions:
                captured_actions.append((phase, a))
            return orig_drain(self, actions, phase=phase)

        with patch.object(_Exec, "drain", _capture):
            try:
                up_mod.up(args)
            except SystemExit:
                pass

        mock_gen_res.assert_called_with("1.5", "2G", "ag-xfce-ssh")

        from sanity_gravity.effects.actions import RunSubprocess
        up_actions = [
            a for _, a in captured_actions
            if isinstance(a, RunSubprocess)
            and "up" in a.argv and "-d" in a.argv
        ]
        assert len(up_actions) > 0
        argv = up_actions[0].argv
        assert "config/docker-compose.resources.yml" in argv


class TestNewCommands:
    """Tests for shell and open commands."""

    @patch("sanity_gravity.verbs.shell.get_project_env", return_value={})
    @patch("sanity_gravity.verbs.shell.run_command")
    @patch("subprocess.check_call")
    def test_shell_command(self, mock_check_call, mock_run, mock_env):
        mock_run.return_value = "true"

        args = argparse.Namespace(name="sanity-gravity", user=None)

        with patch(
            "sanity_gravity.verbs.shell.get_active_projects",
            return_value=["sanity-gravity"],
        ):
            shell_mod.shell_cmd(args)

            expected_cmd = ("docker", "exec", "-it", "-u", "developer",
                            "sanity-gravity-ag-xfce-kasm-1", "zsh")
            mock_check_call.assert_called_with(expected_cmd)

    @patch("sanity_gravity.verbs.shell.get_project_env", return_value={})
    @patch("sanity_gravity.verbs.shell.run_command")
    @patch("subprocess.check_call")
    def test_shell_command_with_user(self, mock_check_call, mock_run, mock_env):
        mock_run.return_value = "true"

        args = argparse.Namespace(name="sanity-gravity", user="root")

        with patch(
            "sanity_gravity.verbs.shell.get_active_projects",
            return_value=["sanity-gravity"],
        ):
            shell_mod.shell_cmd(args)

            expected_cmd = ("docker", "exec", "-it", "-u", "root",
                            "sanity-gravity-ag-xfce-kasm-1", "zsh")
            mock_check_call.assert_called_with(expected_cmd)

    @patch("sanity_gravity.verbs.shell.get_project_env", return_value={})
    @patch("sanity_gravity.verbs.shell.run_command")
    @patch("subprocess.check_call")
    def test_shell_command_with_use_bash(self, mock_check_call, mock_run, mock_env):
        mock_run.return_value = "true"

        args = argparse.Namespace(name="sanity-gravity", user=None, use="bash")

        with patch(
            "sanity_gravity.verbs.shell.get_active_projects",
            return_value=["sanity-gravity"],
        ):
            shell_mod.shell_cmd(args)

            expected_cmd = ("docker", "exec", "-it", "-u", "developer",
                            "sanity-gravity-ag-xfce-kasm-1", "bash")
            mock_check_call.assert_called_with(expected_cmd)

    @patch("sanity_gravity.verbs.shell.get_project_env", return_value={})
    @patch("sanity_gravity.verbs.shell.run_command")
    @patch("subprocess.check_call")
    @patch("subprocess.call")
    def test_shell_command_zsh_fallback_to_bash(
        self, mock_call, mock_check_call, mock_run, mock_env
    ):
        mock_run.return_value = "true"
        mock_check_call.side_effect = subprocess.CalledProcessError(1, "zsh")

        args = argparse.Namespace(name="sanity-gravity", user=None)

        with patch(
            "sanity_gravity.verbs.shell.get_active_projects",
            return_value=["sanity-gravity"],
        ):
            shell_mod.shell_cmd(args)

            mock_check_call.assert_any_call(
                ("docker", "exec", "-it", "-u", "developer",
                 "sanity-gravity-ag-xfce-kasm-1", "zsh")
            )
            mock_call.assert_called_once_with(
                ("docker", "exec", "-it", "-u", "developer",
                 "sanity-gravity-ag-xfce-kasm-1", "bash")
            )

    @patch("sanity_gravity.verbs.shell.get_project_env", return_value={})
    @patch("sanity_gravity.verbs.shell.run_command")
    @patch("subprocess.check_call")
    @patch("subprocess.call")
    def test_shell_command_no_fallback_when_use_specified(
        self, mock_call, mock_check_call, mock_run, mock_env
    ):
        mock_run.return_value = "true"
        mock_check_call.side_effect = subprocess.CalledProcessError(1, "zsh")

        args = argparse.Namespace(name="sanity-gravity", user=None, use="zsh")

        with patch(
            "sanity_gravity.verbs.shell.get_active_projects",
            return_value=["sanity-gravity"],
        ):
            shell_mod.shell_cmd(args)

            mock_check_call.assert_any_call(
                ("docker", "exec", "-it", "-u", "developer",
                 "sanity-gravity-ag-xfce-kasm-1", "zsh")
            )
            mock_call.assert_not_called()

    @patch("sanity_gravity.verbs.open.run_command")
    @patch("webbrowser.open")
    def test_open_command_kasm(self, mock_browser, mock_run):
        def run_side_effect(cmd, **kwargs):
            cmd_str = (
                " ".join(cmd) if isinstance(cmd, (list, tuple)) else cmd
            )
            if "ag-xfce-kasm-1" in cmd_str and "inspect" in cmd_str:
                return "true"
            if "inspect" in cmd_str:
                return "false"
            if "port ag-xfce-kasm 8444" in cmd_str:
                return "0.0.0.0:12345"
            return ""
        mock_run.side_effect = run_side_effect

        args = MagicMock()
        args.name = "sanity-gravity"
        with patch(
            "sanity_gravity.verbs.open.get_active_projects",
            return_value=["sanity-gravity"],
        ):
            open_mod.open_cmd(args)

            mock_browser.assert_called_with("https://localhost:12345")


class TestSnapshot:
    """Tests for snapshot and image features."""

    @patch("sanity_gravity.hooks.snapshot.run_command")
    def test_snapshot_command(self, mock_run):
        # docker inspect → return non-empty so the container is "found".
        mock_run.return_value = '[{"Id": "abc"}]'

        # Use a real-looking args; dry_run=True so the kernel emits a
        # WouldExecute event for the docker commit (no real subprocess).
        args = MagicMock()
        args.name = "my-proj"
        args.variant = "ag-xfce-ssh"
        args.tag = "my-image:v1"
        args.dry_run = False
        # Use a real reporter instance so .info / .header / .success exist.
        from sanity_gravity.core.reporter import Reporter
        args.reporter = Reporter(sinks=[], run_id="test")

        from sanity_gravity.effects.actions import RunSubprocess
        from sanity_gravity.hooks import snapshot as sh

        captured: list = []

        # Stub the executor so we don't actually run docker commit.
        with patch.object(
            sh, "register_builtin_snapshot_hooks",
            wraps=sh.register_builtin_snapshot_hooks,
        ):
            with patch(
                "sanity_gravity.verbs.snapshot.build_default_executor"
            ) as mk_exec:
                fake_exec = MagicMock()
                fake_exec.drain.side_effect = lambda actions, phase=None: captured.extend(actions)
                fake_exec.close = lambda: None
                mk_exec.return_value = fake_exec
                snapshot_mod.snapshot_cmd(args)

        # The plan must have inspected the container.
        flat_inspect = [
            " ".join(c.args[0]) if isinstance(c.args[0], (list, tuple)) else c.args[0]
            for c in mock_run.call_args_list
        ]
        assert any("docker inspect my-proj-ag-xfce-ssh-1" in c for c in flat_inspect)
        # And queued exactly one docker commit Action.
        commits = [
            a for a in captured
            if isinstance(a, RunSubprocess) and "commit" in a.argv
        ]
        assert len(commits) == 1
        assert commits[0].argv == (
            "docker", "commit", "my-proj-ag-xfce-ssh-1", "my-image:v1",
        )

    @patch("sanity_gravity.verbs.up.run_command")
    @patch("sanity_gravity.verbs.up.get_uid_gid_user", return_value=(1000, 1000, "dev"))
    @patch("sanity_gravity.compose.generators.ProxyManager")
    def test_up_with_custom_image(self, mock_pm, mock_user, mock_run):
        mock_instance = mock_pm.return_value
        mock_instance.is_enabled.return_value = False
        with patch.dict(os.environ, {}, clear=True):
            args = MagicMock()
            args.variant = "ag-xfce-ssh"
            args.skip_check = True
            args.ssh_port = "2222"
            args.kasm_port = "8444"
            args.vnc_port = "5901"
            args.novnc_port = "6901"
            args.workspace = None
            args.name = "sanity-gravity"
            args.password = "pass"
            args.cpus = None
            args.memory = None

            args.image = "my-custom:v1"
            args.pull = False
            args.dry_run = True

            up_mod.up(args)

            assert os.environ.get("SANITY_IMAGE_AG_XFCE_SSH") == "my-custom:v1"
