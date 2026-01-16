import pytest
import sys
import os
import importlib.util
from unittest.mock import patch, MagicMock, call

from importlib.machinery import SourceFileLoader

# Helper to import sanity-cli as a module
def load_sanity_cli():
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
        # Format: project_name|image_name
        mock_output = """project-a|sanity-gravity:core
project-b|sanity-gravity:kasm
other-project|nginx:latest
project-c|sanity-gravity:vnc"""
        
        mock_run.return_value = mock_output
        
        projects = sanity_cli.get_active_projects()
        
        # Should only include projects with sanity-gravity images
        assert "project-a" in projects
        assert "project-b" in projects
        assert "project-c" in projects
        assert "other-project" not in projects
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
            
            # Verify docker commands (mkdir and cp)
            # We expect: mkdir -p ... and docker cp config/. ...
            docker_cmds = [args[0][0] for args in mock_run.call_args_list]
            assert any("docker cp config/." in cmd for cmd in docker_cmds)
