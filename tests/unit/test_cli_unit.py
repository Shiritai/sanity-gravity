"""CLI-level unit tests for sanity-cli verbs and registry projections.

The tests exercise the new :mod:`sanity_gravity` package directly. Every
subprocess outcome is scripted through the shared ``fake_proc`` fixture,
which fakes the whole ``core.proc`` boundary (``try_run`` / ``capture`` /
``run_shell``) and patches those names wherever a module imported them
into its own namespace. A command no test scripted is an error, not a
silent rc=0 -- the shape that lets a test go green while asserting
nothing.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sanity_gravity.core.registry import (
    AGENTS,
    CONNECTORS,
    DESKTOPS,
    VALID_TAGS,
    resolve_tag,
)
from sanity_gravity.domain.layers import LayerRef
from sanity_gravity.domain.tags import Tag
from sanity_gravity.hooks.build import _bind
from sanity_gravity.verbs import lifecycle as lifecycle_mod
from sanity_gravity.verbs import open as open_mod
from sanity_gravity.verbs import shell as shell_mod
from sanity_gravity.verbs import snapshot as snapshot_mod
from sanity_gravity.verbs import sync as sync_mod
from sanity_gravity.verbs import up as up_mod
from sanity_gravity.verbs.build import generate_intermediates
from tests.conftest import container_record

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


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
            resolve_tag("ag-none-ssh")

    def test_gui_connector_requires_gui_desktop(self):
        """kasm/vnc connectors must have a GUI desktop."""
        for connector in ["kasm", "vnc"]:
            with pytest.raises(ValueError, match="requires a GUI desktop"):
                resolve_tag(f"gc-none-{connector}")

    def test_headless_cli_agents_valid(self):
        """gc and cc can run headless with SSH."""
        for agent in ["gc", "cc"]:
            parsed = resolve_tag(f"{agent}-none-ssh")
            assert parsed.agent == agent
            assert parsed.desktop == "none"
            assert parsed.connector == "ssh"

    def test_all_ag_tags_have_xfce(self):
        """Every ag tag must use xfce desktop."""
        ag_tags = [t for t in VALID_TAGS if resolve_tag(t).agent == "ag"]
        assert len(ag_tags) == 3
        for tag in ag_tags:
            assert "-xfce-" in tag

    def test_no_headless_gui_connector_in_valid_tags(self):
        """No *-none-kasm/vnc should appear in VALID_TAGS."""
        from sanity_gravity.domain.tags import Tag

        for tag in VALID_TAGS:
            t = Tag.parse(tag)
            if t.desktop == "none":
                assert t.connector == "ssh", f"Invalid combo in VALID_TAGS: {tag}"

    def test_registry_attributes(self):
        """Registries should have correct attribute structure."""
        for info in AGENTS.values():
            assert "name" in info
            assert "requires_gui" in info
        for info in CONNECTORS.values():
            assert "name" in info
            assert "requires_gui" in info
        for info in DESKTOPS.values():
            assert "name" in info
            assert "has_gui" in info

    def test_unknown_agent_rejected(self):
        with pytest.raises(ValueError, match="Unknown agent"):
            resolve_tag("bs-xfce-ssh")

    def test_invalid_format_rejected(self):
        with pytest.raises(ValueError, match="Invalid tag format"):
            resolve_tag("ag-xfce")
        with pytest.raises(ValueError, match="Invalid tag format"):
            resolve_tag("ag-xfce-kasm-extra")


class TestLayeredBuildSystem:
    """Tests for the FROM-chained layered build structure.

    Asserts identity (LayerRef), not plan shape: the rendered command
    sequences are pinned by the golden master (test_build_golden.py)."""

    def test_chain_is_base_desktop_agent_connector(self):
        ref = LayerRef.of_tag(Tag.parse("gc-none-ssh"))
        assert ref.ancestors == (
            LayerRef.base(),
            LayerRef.of_desktop("none"),
            LayerRef.of_agent("gc", "none"),
        )

    def test_parent_rule(self):
        assert LayerRef.of_tag(Tag.parse("ag-xfce-kasm")).parent == \
            LayerRef.of_agent("ag", "xfce")
        assert LayerRef.of_tag(Tag.parse("cc-xfce-vnc")).parent == \
            LayerRef.of_agent("cc", "xfce")

    def test_shared_intermediates(self):
        """Two connectors on the same agent-desktop share their parent."""
        assert LayerRef.of_tag(Tag.parse("ag-xfce-kasm")).parent == \
            LayerRef.of_tag(Tag.parse("ag-xfce-vnc")).parent

    def test_generate_intermediates(self):
        intermediates = generate_intermediates()
        assert "_base" in intermediates
        assert "_base-xfce" in intermediates
        assert "_base-none" in intermediates
        assert "_ag-xfce" in intermediates
        assert "_cc-xfce" in intermediates
        # gc is tier=deprecated: its intermediates leave the automatic
        # enumeration (explicit ``build gc-*`` still resolves the chain).
        assert "_gc-none" not in intermediates
        for name in intermediates:
            assert name.startswith("_"), f"Non-intermediate in list: {name}"

    def test_intermediates_count(self):
        """At least 8 intermediates."""
        assert len(generate_intermediates()) >= 8

    def test_build_chain_dockerfiles_exist(self):
        """Every layer of every valid tag binds to an existing Dockerfile."""
        for tag in VALID_TAGS:
            ref = LayerRef.of_tag(Tag.parse(tag))
            for layer in (*ref.ancestors, ref):
                dockerfile, _context = _bind(layer)
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
    """Tests for get_active_projects function.

    ``get_active_projects`` speaks ``capture``: stdout is the value and a
    docker failure raises rather than collapsing into "no projects".
    """

    def test_get_active_projects_discovery(self, fake_proc):
        fake_proc.script("docker ps", stdout="project-a\nproject-b\nproject-c")

        projects = lifecycle_mod.get_active_projects()

        assert "project-a" in projects
        assert "project-b" in projects
        assert "project-c" in projects
        assert len(projects) == 3

    def test_get_active_projects_empty(self, fake_proc):
        """Ok("") is the legitimate domain answer: no projects."""
        fake_proc.script("docker ps", stdout="")
        assert lifecycle_mod.get_active_projects() == []

    def test_get_active_projects_error_raises(self, fake_proc):
        from sanity_gravity.domain.errors import CommandError

        # rc drives it: the fake capture raises exactly as the real one
        # does, so Err is not collapsed into the Ok-empty value.
        fake_proc.script("docker ps", rc=1, stderr="daemon down")
        with pytest.raises(CommandError):
            lifecycle_mod.get_active_projects()


class TestConfigSync:
    """Tests for sync_config function.

    ``sync_config`` speaks both proc intents it needs: try_run for the
    user-poll / mkdir / chown calls, run_shell for the tar pipe.
    ``fake_proc`` records both in one ordered list, so ordering and
    content assertions read the same way for either intent. The
    filesystem side (exists / makedirs / copy2) is still simulated with
    mocks: it is not the subprocess boundary.
    """

    #: A container name that genuinely needs shell quoting. A plain name
    #: like "test-container" is returned UNCHANGED by shlex.quote, so it
    #: cannot tell a quoted rendering apart from an unquoted one -- which
    #: is precisely why the old assertion here accepted both spellings
    #: and could never fail.
    UNSAFE_CONTAINER = "proj; rm -rf /"
    QUOTED_CONTAINER = "'proj; rm -rf /'"

    @pytest.fixture
    def mock_env(self, fake_proc):
        """Filesystem mocks + the docker answers sync_config expects."""
        # The poll answers a uid; mkdir/chown succeed quietly. mkdir runs
        # with capture=False, so it is scripted with an rc only.
        fake_proc.script("id -u", stdout="1000")
        fake_proc.script("mkdir -p")
        fake_proc.script("chown -R")
        fake_proc.script("tar -cf -")  # the run_shell pipe

        with patch("os.path.exists") as mock_exists, \
             patch("os.makedirs") as mock_makedirs, \
             patch("shutil.copy2") as mock_copy, \
             patch("builtins.print"):
            yield mock_exists, mock_makedirs, mock_copy, fake_proc

    def test_sync_config_non_interactive(self, mock_env):
        mock_exists, _, _, fake_proc = mock_env

        mock_exists.side_effect = lambda p: p != "config"

        with patch("sys.stdin.isatty", return_value=False):
            sync_mod.sync_config("test-proj", "test-container", "user")

            fake_proc.assert_never_ran("docker cp")

    def test_sync_config_interactive_copy(self, mock_env):
        mock_exists, mock_makedirs, mock_copy, _ = mock_env

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

    def test_sync_config_interactive_flow(self, mock_env):
        mock_exists, mock_makedirs, mock_copy, fake_proc = mock_env
        fs_state = {"config": False}

        def exists_mock(path):
            if path == "config":
                return fs_state["config"]
            if ".gemini" in path:
                return True
            return False

        def makedirs_mock(path, exist_ok=True):
            if path == "config":
                fs_state["config"] = True

        mock_exists.side_effect = exists_mock
        mock_makedirs.side_effect = makedirs_mock

        with patch("sys.stdin.isatty", return_value=True), \
             patch("builtins.input", return_value="a"):

            sync_mod.sync_config("test-proj", self.UNSAFE_CONTAINER, "user")

            assert mock_copy.call_count >= 2

            assert fake_proc.ran("tar -cf -")
            # The container name is interpolated into a genuine shell
            # command, so it must arrive shlex.quote()d. Pinned as the
            # exact quoted literal: accepting the bare spelling as well
            # would accept a command injection.
            pipe = fake_proc.assert_ran("tar -cf -").text
            assert f"docker exec -i {self.QUOTED_CONTAINER} tar -xf -" in pipe
            assert f"docker exec -i {self.UNSAFE_CONTAINER} tar" not in pipe

    def test_config_dir_is_shell_quoted_in_the_tar_pipe(self, mock_env):
        """The other interpolated value in the same pipe. Same reasoning:
        a path with a space or a ';' must not be re-parsed by the shell."""
        mock_exists, _, _, fake_proc = mock_env
        unsafe_dir = "/tmp/my configs; touch pwned"

        mock_exists.side_effect = lambda p: p == unsafe_dir
        sync_mod.sync_config(
            "p", "c", "user", config_source=unsafe_dir,
        )

        pipe = fake_proc.assert_ran("tar -cf -").text
        assert "tar -cf - -C '/tmp/my configs; touch pwned'" in pipe

    def test_sync_config_safe_simulation(self, mock_env):
        """Test sync_config with a custom source directory (simulation)."""
        mock_exists, _, _, fake_proc = mock_env
        with tempfile.TemporaryDirectory() as temp_config_dir:
            gemini_path = os.path.join(temp_config_dir, "GEMINI.md")
            with open(gemini_path, "w") as f:
                f.write("# Safe Simulation Test")
            mock_exists.side_effect = lambda p: p == temp_config_dir

            sync_mod.sync_config(
                "safe-proj", "safe-container", "user",
                config_source=temp_config_dir,
            )

            import shlex as _shlex
            expected_tar_part = (
                f"tar -cf - -C {_shlex.quote(temp_config_dir)}"
            )

            tar_commands = fake_proc.calls_matching("tar -cf -")

            assert len(tar_commands) > 0, "No tar sync command found"
            assert any(expected_tar_part in c.text for c in tar_commands)

            assert fake_proc.ran("mkdir -p /home/user/.gemini")
            assert fake_proc.ran("chown -R user:user /home/user/.gemini")

    def test_user_poll_requires_a_uid_not_just_rc_zero(self, mock_env,
                                                       monkeypatch):
        """``docker exec ... id -u`` answering rc=0 with EMPTY stdout is
        not proof the user exists.

        Guards ``if res.ok and res.stdout.isdigit()``. Keying on the rc
        alone would declare the user ready on the first poll, so the
        30s timeout warning -- the only signal the sync is about to land
        in a container without that user -- would never be emitted.
        """
        mock_exists, _, _, fake_proc = mock_env
        # The poll sleeps a second per attempt; the property under test
        # is the predicate, not the wall clock.
        monkeypatch.setattr(sync_mod.time, "sleep", lambda _s: None)
        fake_proc.script("id -u", rc=0, stdout="")

        with tempfile.TemporaryDirectory() as temp_config_dir:
            mock_exists.side_effect = lambda p: p == temp_config_dir
            with patch.object(sync_mod, "print_warning") as warn:
                sync_mod.sync_config(
                    "p", "c", "user", config_source=temp_config_dir,
                )

        warned = [c.args[0] for c in warn.call_args_list]
        assert any("not found in container after 30s" in w for w in warned)
        # ...and it really did keep polling rather than accepting the
        # first empty answer.
        assert len(fake_proc.calls_matching("id -u")) == 30

    def test_chown_failure_warns_on_rc(self, mock_env):
        """chown reports failure on STDERR + rc; the old code keyed the
        warning on stdout, so a real failure printed 'synced
        successfully'. The rc now drives the warning."""
        mock_exists, _, _, fake_proc = mock_env
        fake_proc.script("chown -R", rc=1, stderr="chown: invalid user")

        with tempfile.TemporaryDirectory() as temp_config_dir:
            mock_exists.side_effect = lambda p: p == temp_config_dir
            with patch.object(sync_mod, "print_warning") as warn:
                sync_mod.sync_config(
                    "p", "c", "user", config_source=temp_config_dir,
                )
        warned = [c.args[0] for c in warn.call_args_list]
        assert any("Failed to set permissions" in w for w in warned)
        assert any("chown: invalid user" in w for w in warned)

    def test_chown_failure_never_claims_success(self, mock_env):
        """A failed chown must not be followed by 'synced successfully':
        the closing line is the one the user acts on, so it has to be
        keyed on the same rc the warning is keyed on."""
        mock_exists, _, _, fake_proc = mock_env
        fake_proc.script("chown -R", rc=1, stderr="chown: invalid user")

        with tempfile.TemporaryDirectory() as temp_config_dir:
            mock_exists.side_effect = lambda p: p == temp_config_dir
            with patch.object(sync_mod, "print_warning") as warn, \
                 patch.object(sync_mod, "print_success") as ok:
                sync_mod.sync_config(
                    "p", "c", "user", config_source=temp_config_dir,
                )
        claimed = [c.args[0] for c in ok.call_args_list]
        assert not any("synced successfully" in s for s in claimed), (
            "sync declared success after a failed chown"
        )
        warned = [c.args[0] for c in warn.call_args_list]
        assert any("ownership" in w for w in warned)

    def test_chown_success_still_claims_success(self, mock_env):
        """The success line survives on the happy path."""
        mock_exists, _, _, _ = mock_env
        with tempfile.TemporaryDirectory() as temp_config_dir:
            mock_exists.side_effect = lambda p: p == temp_config_dir
            with patch.object(sync_mod, "print_success") as ok:
                sync_mod.sync_config(
                    "p", "c", "user", config_source=temp_config_dir,
                )
        claimed = [c.args[0] for c in ok.call_args_list]
        assert any("synced successfully" in s for s in claimed)

    def test_chown_stdout_chatter_with_rc_zero_does_not_warn(self, mock_env):
        """The flip side of the stdout-keyed warning: rc==0 with stdout
        chatter used to trigger a bogus 'Failed to set permissions'."""
        mock_exists, _, _, fake_proc = mock_env
        fake_proc.script("chown -R", rc=0, stdout="some chatter")

        with tempfile.TemporaryDirectory() as temp_config_dir:
            mock_exists.side_effect = lambda p: p == temp_config_dir
            with patch.object(sync_mod, "print_warning") as warn:
                sync_mod.sync_config(
                    "p", "c", "user", config_source=temp_config_dir,
                )
        warned = [c.args[0] for c in warn.call_args_list]
        assert not any("Failed to set permissions" in w for w in warned)



class TestRunResourceArgs:
    """Tests for resource quota arguments."""

    @pytest.fixture(autouse=True)
    def _isolate_cwd(self, tmp_path, monkeypatch):
        # up() runs the real compose generators, which write
        # ./config/*.yml and ./workspace/ relative to the CWD. Without
        # this the unit suite dirties the working tree it runs in.
        monkeypatch.chdir(tmp_path)

    @patch("sanity_gravity.verbs.up.get_uid_gid_user", return_value=(1000, 1000, "dev"))
    @patch("sanity_gravity.verbs.up.generate_resource_compose")
    @patch("sanity_gravity.compose.generators.ProxyManager")
    def test_run_with_resources(self, mock_pm, mock_gen_res, mock_user,
                                fake_proc):
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


_RUNNING_MATCH = [container_record("ag-xfce-kasm")]


class TestNewCommands:
    """Tests for shell and open commands.

    ``shell`` execs interactively through ``subprocess.check_call`` /
    ``call`` rather than the proc boundary (it hands the tty to the
    child), so those stay patched directly.
    """

    @patch("sanity_gravity.verbs.shell.get_project_env", return_value={})
    @patch("sanity_gravity.verbs.shell.find_project_containers")
    @patch("subprocess.check_call")
    def test_shell_command(self, mock_check_call, mock_run, mock_env):
        mock_run.return_value = _RUNNING_MATCH

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
    @patch("sanity_gravity.verbs.shell.find_project_containers")
    @patch("subprocess.check_call")
    def test_shell_command_with_user(self, mock_check_call, mock_run, mock_env):
        mock_run.return_value = _RUNNING_MATCH

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
    @patch("sanity_gravity.verbs.shell.find_project_containers")
    @patch("subprocess.check_call")
    def test_shell_command_with_use_bash(self, mock_check_call, mock_run, mock_env):
        mock_run.return_value = _RUNNING_MATCH

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
    @patch("sanity_gravity.verbs.shell.find_project_containers")
    @patch("subprocess.check_call")
    @patch("subprocess.call")
    def test_shell_command_zsh_fallback_to_bash(
        self, mock_call, mock_check_call, mock_run, mock_env
    ):
        mock_run.return_value = _RUNNING_MATCH
        mock_check_call.side_effect = subprocess.CalledProcessError(1, "zsh")
        mock_call.return_value = 0  # bash fallback succeeds

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
    @patch("sanity_gravity.verbs.shell.find_project_containers")
    @patch("subprocess.check_call")
    @patch("subprocess.call")
    def test_shell_command_no_fallback_when_use_specified(
        self, mock_call, mock_check_call, mock_run, mock_env
    ):
        mock_run.return_value = _RUNNING_MATCH
        mock_check_call.side_effect = subprocess.CalledProcessError(1, "zsh")

        args = argparse.Namespace(name="sanity-gravity", user=None, use="zsh")

        from sanity_gravity.domain.errors import SanityError

        with patch(
            "sanity_gravity.verbs.shell.get_active_projects",
            return_value=["sanity-gravity"],
        ):
            # An explicitly chosen shell that fails is a real failure:
            # no fallback, and the child's rc becomes the exit code.
            with pytest.raises(SanityError) as ei:
                shell_mod.shell_cmd(args)
            assert ei.value.exit_code == 1

            mock_check_call.assert_any_call(
                ("docker", "exec", "-it", "-u", "developer",
                 "sanity-gravity-ag-xfce-kasm-1", "zsh")
            )
            mock_call.assert_not_called()

    @patch("sanity_gravity.verbs.open.find_project_containers")
    @patch("webbrowser.open")
    def test_open_command_kasm(self, mock_browser, mock_find, fake_proc):
        mock_find.return_value = _RUNNING_MATCH
        fake_proc.script("port ag-xfce-kasm 8444", stdout="0.0.0.0:12345")

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

    @pytest.fixture(autouse=True)
    def _isolate_cwd(self, tmp_path, monkeypatch):
        # As in TestRunResourceArgs: up() writes ./config and ./workspace
        # relative to the CWD via the real compose generators.
        monkeypatch.chdir(tmp_path)

    def test_snapshot_command(self, fake_proc):
        # docker inspect -> succeed so the container is "found".
        fake_proc.script("docker inspect", stdout='[{"Id": "abc"}]')

        # Use a real-looking args; dry_run=False so the kernel enqueues
        # the docker commit action (the executor is stubbed below, so
        # nothing runs).
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
        assert fake_proc.ran("docker inspect my-proj-ag-xfce-ssh-1")
        # And queued exactly one docker commit Action.
        commits = [
            a for a in captured
            if isinstance(a, RunSubprocess) and "commit" in a.argv
        ]
        assert len(commits) == 1
        assert commits[0].argv == (
            "docker", "commit", "my-proj-ag-xfce-ssh-1", "my-image:v1",
        )

    @patch("sanity_gravity.verbs.up.get_uid_gid_user", return_value=(1000, 1000, "dev"))
    @patch("sanity_gravity.compose.generators.ProxyManager")
    def test_up_with_custom_image(self, mock_pm, mock_user, fake_proc):
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
