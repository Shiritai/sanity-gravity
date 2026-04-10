import argparse
import pytest
import subprocess
import sys
import os
import importlib.util
from unittest.mock import patch, MagicMock, call

from importlib.machinery import SourceFileLoader

# Helper to import sanity-cli as a module
def load_sanity_cli():
    if "sanity_cli" in sys.modules:
        return sys.modules["sanity_cli"]
        
    file_path = os.path.abspath("sanity-cli")
    # SourceFileLoader works even without .py extension
    loader = SourceFileLoader("sanity_cli", file_path)
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("sanity_cli", loader))
    sys.modules["sanity_cli"] = module
    loader.exec_module(module)
    return module

sanity_cli = load_sanity_cli()

class TestStatusDiscovery:
    """Tests for get_active_projects function."""

    @patch("sanity_cli.run_command")
    def test_get_active_projects_discovery(self, mock_run):
        # Mock docker ps output
        # Current logic uses 'docker ps --filter label=...' and expects just project names
        mock_output = """project-a
project-b
project-c"""
        
        mock_run.return_value = mock_output
        
        projects = sanity_cli.get_active_projects()
        
        # Verify projects are parsed correctly
        assert "project-a" in projects
        assert "project-b" in projects
        assert "project-c" in projects
        assert len(projects) == 3
        
    @patch("sanity_cli.run_command")
    def test_get_active_projects_empty(self, mock_run):
        mock_run.return_value = ""
        projects = sanity_cli.get_active_projects()
        assert projects == []

    @patch("sanity_cli.run_command")
    def test_get_active_projects_error(self, mock_run):
        mock_run.side_effect = Exception("Docker error")
        projects = sanity_cli.get_active_projects()
        assert projects == []

class TestConfigSync:
    """Tests for sync_config function."""

    @pytest.fixture
    def mock_env(self):
        with patch("os.path.exists") as mock_exists, \
             patch("os.makedirs") as mock_makedirs, \
             patch("shutil.copy2") as mock_copy, \
             patch("sanity_cli.run_command") as mock_run, \
             patch("builtins.print") as mock_print:
            yield mock_exists, mock_makedirs, mock_copy, mock_run, mock_print

    def test_sync_config_non_interactive(self, mock_env):
        mock_exists, _, _, mock_run, _ = mock_env
        
        # Simulate config dir missing
        mock_exists.side_effect = lambda p: p != "config"
        
        # Simulate non-interactive TTY
        with patch("sys.stdin.isatty", return_value=False):
            sanity_cli.sync_config("test-proj", "test-container", "user")
            
            # Should NOT call input
            # Should NOT call docker cp (since it skips)
            # Verify no docker cp command was run
            for call_args in mock_run.call_args_list:
                cmd = call_args[0][0]
                assert "docker cp" not in cmd

    def test_sync_config_interactive_copy(self, mock_env):
        mock_exists, mock_makedirs, mock_copy, mock_run, _ = mock_env
        
        # Simulate config dir missing, but ~/.gemini files exist
        def exists_side_effect(path):
            if path == "config": return False
            if "GEMINI.md" in path: return True
            if "settings.json" in path: return True
            return False
        mock_exists.side_effect = exists_side_effect
        
        # Simulate interactive TTY and user input 'a'
        with patch("sys.stdin.isatty", return_value=True), \
             patch("builtins.input", return_value="a"):
            
            sanity_cli.sync_config("test-proj", "test-container", "user")
            
            # Should copy files
            assert mock_copy.call_count >= 2 # GEMINI.md and settings.json
            
            # Should sync to container (mocking that config dir exists now? 
            # Logic in sync_config checks os.path.exists(config_dir) AGAIN before syncing.
            # We need to ensure the second check returns True.
            # Side effect is tricky if called multiple times with same arg.
            # Let's assume os.makedirs makes it exist.
            # But os.path.exists is mocked.
            # We can use a side_effect that checks a state variable.
            pass

    # Refined interactive test with state
    def test_sync_config_interactive_flow(self):
        # We need a more complex mock for os.path.exists to simulate directory creation
        fs_state = {"config": False, "home_gemini": True}
        
        def exists_mock(path):
            if path == "config": return fs_state["config"]
            if ".gemini" in path: return True
            return False
            
        def makedirs_mock(path, exist_ok=True):
            if path == "config": fs_state["config"] = True

        with patch("os.path.exists", side_effect=exists_mock), \
             patch("os.makedirs", side_effect=makedirs_mock), \
             patch("shutil.copy2") as mock_copy, \
             patch("sanity_cli.run_command") as mock_run, \
             patch("sys.stdin.isatty", return_value=True), \
             patch("builtins.input", return_value="a"), \
             patch("builtins.print"):
             
            sanity_cli.sync_config("test-proj", "test-container", "user")
            
            # Verify files copied from host
            assert mock_copy.call_count >= 2
            
            # Verify docker commands (mkdir and tar)
            # We expect: mkdir -p ... and tar ... | docker exec -i ...
            docker_cmds = [args[0][0] for args in mock_run.call_args_list]
            assert any("tar -cf -" in cmd for cmd in docker_cmds)
            assert any("docker exec -i test-container tar -xf -" in cmd for cmd in docker_cmds)

    def test_sync_config_safe_simulation(self):
        """Test sync_config with a custom source directory (simulation)."""
        import tempfile
        import shutil
        
        # Create a temporary directory to act as the config source
        with tempfile.TemporaryDirectory() as temp_config_dir:
            # Create a dummy GEMINI.md in it
            gemini_path = os.path.join(temp_config_dir, "GEMINI.md")
            with open(gemini_path, "w") as f:
                f.write("# Safe Simulation Test")
                
            with patch("sanity_cli.run_command") as mock_run, \
                 patch("builtins.print"):
                
                # Call sync_config with the temp dir as source
                sanity_cli.sync_config("safe-proj", "safe-container", "user", config_source=temp_config_dir)
                
                # Check that tar command was called with the temp dir
                docker_cmds = [args[0][0] for args in mock_run.call_args_list]
    
                # We expect: tar -cf - -C {temp_config_dir} ...
                expected_tar_part = f"tar -cf - -C {temp_config_dir}"
    
                # Filter commands that are tar commands
                tar_commands = [cmd for cmd in docker_cmds if "tar -cf -" in cmd]
    
                assert len(tar_commands) > 0, "No tar sync command found"
                assert any(expected_tar_part in cmd for cmd in tar_commands)
                
                # Also verify mkdir and chown calls
                assert any("mkdir -p /home/user/.gemini" in cmd for cmd in docker_cmds)
                assert any("chown -R user:user /home/user/.gemini" in cmd for cmd in docker_cmds)

class TestRunResourceArgs:
    """Tests for resource quota arguments."""
    
    @patch("sanity_cli.run_command")
    @patch("sanity_cli.get_uid_gid_user", return_value=(1000, 1000, "dev"))
    @patch("sanity_cli.generate_resource_compose")
    @patch("sanity_cli.ProxyManager")
    def test_run_with_resources(self, mock_pm, mock_gen_res, mock_user, mock_run):
        # Mock Proxy disabled
        mock_instance = mock_pm.return_value
        mock_instance.is_enabled.return_value = False
        # Setup mocks
        mock_gen_res.return_value = "config/docker-compose.resources.yml"
        
        args = MagicMock()
        args.variant = "ag-xfce-ssh"
        args.cpus = "1.5"
        args.memory = "2G"
        # set other defaults
        args.skip_check = True
        args.ssh_port = "2222"
        args.kasm_port = "8444"
        args.vnc_port = "5901"
        args.novnc_port = "6901"
        args.workspace = None
        args.name = "sanity-gravity"
        args.gpu = False
        args.password = "pass"
        args.image = None

        sanity_cli.up(args)

        # Verify generate_resource_compose called
        mock_gen_res.assert_called_with("1.5", "2G", "ag-xfce-ssh")
        
        # Verify docker compose command includes the new file
        # We need to check all calls to run_command
        # Look for the one that has 'up -d'
        up_calls = [args[0][0] for args in mock_run.call_args_list if "up -d" in args[0][0]]
        assert len(up_calls) > 0
        cmd = up_calls[0]
        assert "-f config/docker-compose.resources.yml" in cmd

class TestNewCommands:
    """Tests for shell and open commands."""
    
    @patch("sanity_cli.run_command")
    @patch("subprocess.check_call")
    def test_shell_command(self, mock_check_call, mock_run):
        # Mock finding container
        mock_run.return_value = "true" # docker inspect running

        args = argparse.Namespace(name="sanity-gravity", user=None)

        with patch("sanity_cli.get_active_projects", return_value=["sanity-gravity"]):
            sanity_cli.shell_cmd(args)

            # Check if docker exec was called
            # It finds the first running container from VALID_TAGS (ag-xfce-ssh)
            # developer is default user, zsh is default shell
            expected_cmd = "docker exec -it -u developer sanity-gravity-ag-xfce-ssh-1 zsh"
            mock_check_call.assert_called_with(expected_cmd, shell=True)

    @patch("sanity_cli.run_command")
    @patch("subprocess.check_call")
    def test_shell_command_with_user(self, mock_check_call, mock_run):
        # Mock finding container
        mock_run.return_value = "true"

        args = argparse.Namespace(name="sanity-gravity", user="root")

        with patch("sanity_cli.get_active_projects", return_value=["sanity-gravity"]):
            sanity_cli.shell_cmd(args)

            # Verify user passed to docker exec
            expected_cmd = "docker exec -it -u root sanity-gravity-ag-xfce-ssh-1 zsh"
            mock_check_call.assert_called_with(expected_cmd, shell=True)

    @patch("sanity_cli.run_command")
    @patch("subprocess.check_call")
    def test_shell_command_with_use_bash(self, mock_check_call, mock_run):
        # User explicitly selects bash via --use
        mock_run.return_value = "true"

        args = argparse.Namespace(name="sanity-gravity", user=None, use="bash")

        with patch("sanity_cli.get_active_projects", return_value=["sanity-gravity"]):
            sanity_cli.shell_cmd(args)

            expected_cmd = "docker exec -it -u developer sanity-gravity-ag-xfce-ssh-1 bash"
            mock_check_call.assert_called_with(expected_cmd, shell=True)

    @patch("sanity_cli.run_command")
    @patch("subprocess.check_call")
    @patch("subprocess.call")
    def test_shell_command_zsh_fallback_to_bash(self, mock_call, mock_check_call, mock_run):
        # No --use specified: zsh fails, should fall back to bash
        mock_run.return_value = "true"
        mock_check_call.side_effect = subprocess.CalledProcessError(1, "zsh")

        args = argparse.Namespace(name="sanity-gravity", user=None)

        with patch("sanity_cli.get_active_projects", return_value=["sanity-gravity"]):
            sanity_cli.shell_cmd(args)

            mock_check_call.assert_any_call(
                "docker exec -it -u developer sanity-gravity-ag-xfce-ssh-1 zsh", shell=True
            )
            mock_call.assert_called_once_with(
                "docker exec -it -u developer sanity-gravity-ag-xfce-ssh-1 bash", shell=True
            )

    @patch("sanity_cli.run_command")
    @patch("subprocess.check_call")
    @patch("subprocess.call")
    def test_shell_command_no_fallback_when_use_specified(self, mock_call, mock_check_call, mock_run):
        # --use specified: failure should NOT fall back to bash
        mock_run.return_value = "true"
        mock_check_call.side_effect = subprocess.CalledProcessError(1, "zsh")

        args = argparse.Namespace(name="sanity-gravity", user=None, use="zsh")

        with patch("sanity_cli.get_active_projects", return_value=["sanity-gravity"]):
            sanity_cli.shell_cmd(args)

            mock_check_call.assert_any_call(
                "docker exec -it -u developer sanity-gravity-ag-xfce-ssh-1 zsh", shell=True
            )
            mock_call.assert_not_called()

    @patch("sanity_cli.run_command")
    @patch("webbrowser.open")
    def test_open_command_kasm(self, mock_browser, mock_run):
         def run_side_effect(cmd, **kwargs):
            if "ag-xfce-kasm-1" in cmd and "inspect" in cmd: return "true"
            if "inspect" in cmd: return "false"
            if "port ag-xfce-kasm 8444" in cmd: return "0.0.0.0:12345"
            return ""
         mock_run.side_effect = run_side_effect
         
         args = MagicMock()
         args.name = "sanity-gravity"
         with patch("sanity_cli.get_active_projects", return_value=["sanity-gravity"]):
             sanity_cli.open_cmd(args)
             
             mock_browser.assert_called_with("https://localhost:12345")

class TestSnapshot:
    """Tests for snapshot and image features."""

    @patch("sanity_cli.run_command")
    def test_snapshot_command(self, mock_run):
        args = MagicMock()
        args.name = "my-proj"
        args.variant = "ag-xfce-ssh"
        args.tag = "my-image:v1"

        sanity_cli.snapshot_cmd(args)

        # Verify docker inspect called
        # Verify docker commit called

        # We expect inspect to verify container exists
        inspect_call = [args[0][0] for args in mock_run.call_args_list if "docker inspect" in args[0][0]]
        assert len(inspect_call) > 0

        # Check commit
        commit_calls = [args[0][0] for args in mock_run.call_args_list if "docker commit" in args[0][0]]
        assert len(commit_calls) > 0

        expected_commit = "docker commit my-proj-ag-xfce-ssh-1 my-image:v1"
        assert expected_commit in commit_calls[0]

    @patch("sanity_cli.run_command")
    @patch("sanity_cli.get_uid_gid_user", return_value=(1000, 1000, "dev"))
    @patch("sanity_cli.ProxyManager")
    def test_up_with_custom_image(self, mock_pm, mock_user, mock_run):
        # Mock Proxy disabled
        mock_instance = mock_pm.return_value
        mock_instance.is_enabled.return_value = False
        # Override os.environ to avoid polluting actual env
        with patch.dict(os.environ, {}, clear=True):
            args = MagicMock()
            args.variant = "ag-xfce-ssh"
            # set other defaults
            args.skip_check = True
            args.ssh_port = "2222"
            args.kasm_port = "8444"
            args.vnc_port = "5901"
            args.novnc_port = "6901"
            args.workspace = None
            args.name = "sanity-gravity"
            args.gpu = False
            args.password = "pass"
            args.cpus = None
            args.memory = None

            # The key arg
            args.image = "my-custom:v1"

            sanity_cli.up(args)

            assert os.environ.get("SANITY_IMAGE_AG_XFCE_SSH") == "my-custom:v1"
