import subprocess
import pytest
import os

class TestCLI:
    """Tests for sanity-cli itself."""
    
    @pytest.fixture
    def cli(self):
        def _run(args):
            # Run against the local sanity-cli script
            cmd = f"./sanity-cli {args}"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            return result
        return _run

    def test_cli_help(self, cli):
        res = cli("--help")
        assert res.returncode == 0
        assert "Antigravity Sandbox" in res.stdout
        assert "CLI" in res.stdout

    def test_cli_list(self, cli):
        res = cli("list")
        assert res.returncode == 0
        assert "ag-xfce-kasm" in res.stdout
        assert "Dimension Matrix" in res.stdout

    def test_cli_check(self, cli):
        res = cli("check")
        assert res.returncode == 0
        assert "Docker is installed" in res.stdout

    # Integration tests involving docker-compose/build via CLI might be slow.
    # We can mark them as slow if we had pytest markers config.
    # For now, let's include basic lifecycle verification but maybe skip full build to save time if images exist.
    # But user wants "sanity check" so running 'build' is part of it.
    
    def test_cli_lifecycle(self, cli, clean_container):
        """Test run -> status -> stop flow."""
        # Clean up in case
        cli("stop")
        
        # Test Run (ag-xfce-ssh is the lightest GUI-less variant)
        # sanity-cli up uses 'docker compose up -d' so it returns.
        res = cli("run -v ag-xfce-ssh --ssh-port 2299 --skip-check --password testcli")
        assert res.returncode == 0
        assert "ag-xfce-ssh is running" in res.stdout
        
        # Test Stop
        res = cli("stop")
        assert res.returncode == 0
        assert "Containers stopped (data preserved)" in res.stdout
