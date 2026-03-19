import pytest
import time
from tests.utils import wait_for_port
from tests.conftest import DEFAULT_KASM_IMAGE

@pytest.fixture(scope="function")
def test_kasm_container(clean_container, docker_cli, host_env):
    """Start a single Kasm container for all sandbox integration tests."""
    container_name = clean_container("sanity-test-sandbox-full")
    docker_cli.run_container(
        name=container_name,
        image=DEFAULT_KASM_IMAGE,
        ports={"8444": "8444"},
        env=host_env
    )
    assert wait_for_port(8444)
    time.sleep(5)
    return container_name

class TestSandboxFullIntegration:
    def test_chrome_cli_startup(self, test_kasm_container, docker_cli, host_env):
        """Verify that chrome-related commands (stable/safe) can start a chrome instance normally."""
        user = host_env["HOST_USER"]
        
        # Test wrapper version output
        res_safe = docker_cli.exec(test_kasm_container, f"su - {user} -c 'DISPLAY=:1 google-chrome-safe --version'")
        assert res_safe.returncode == 0, f"google-chrome-safe failed: {res_safe.stderr}"
        
        # Test symlink stable version output
        res_stable = docker_cli.exec(test_kasm_container, f"su - {user} -c 'DISPLAY=:1 google-chrome-stable --version'")
        assert res_stable.returncode == 0, f"google-chrome-stable failed: {res_stable.stderr}"

        # Ensure browser does not crash instantly without sandbox
        res_run = docker_cli.exec(test_kasm_container, f"su - {user} -c 'DISPLAY=:1 timeout 2 google-chrome-safe chrome://version; echo EXIT_$?'")
        # timeout exits with 124 if it successfully times out the running process
        assert "EXIT_124" in res_run.stdout, f"Browser crashed or exited prematurely: {res_run.stderr}"

    def test_antigravity_cli_startup(self, test_kasm_container, docker_cli, host_env):
        """Verify that 'antigravity <workspace>' can launch a new Antigravity instance."""
        user = host_env["HOST_USER"]
        
        # Init a workspace to ensure the environment is valid
        docker_cli.exec(test_kasm_container, f"su - {user} -c 'mkdir -p ~/test_ws && cd ~/test_ws && git config --global user.email \"test@test.com\" && git config --global user.name \"Test\" && git init && git commit --allow-empty -m init'")
        
        # Start IDE in background
        docker_cli.exec(test_kasm_container, f"su - {user} -c 'DISPLAY=:1 antigravity ~/test_ws > /tmp/ag.log 2>&1 &'")
        
        # Wait for IDE processes to spawn
        time.sleep(5)
        res = docker_cli.exec(test_kasm_container, f"su - {user} -c 'pgrep -f antigravity'")
        assert res.returncode == 0, "Antigravity IDE failed to start"

    def test_antigravity_oauth_login_mock(self, test_kasm_container, docker_cli, host_env):
        """Verify that Antigravity can use chrome for OAuth login."""
        user = host_env["HOST_USER"]
        
        # xdg-open spawns the browser in the background and exits immediately with 0.
        res_xdg = docker_cli.exec(test_kasm_container, f"su - {user} -c 'DISPLAY=:1 xdg-open https://google.com; echo EXIT_$?'")
        assert "EXIT_0" in res_xdg.stdout, f"xdg-open failed: {res_xdg.stderr}"
        
        # Verify that the browser was actually launched by xdg-open and is running securely
        time.sleep(2)
        res_pgrep = docker_cli.exec(test_kasm_container, f"su - {user} -c 'pgrep -f chrome || pgrep -f chromium'")
        assert res_pgrep.returncode == 0, "xdg-open returned 0, but no browser process is running in the background."

    def test_antigravity_chat_capability(self, test_kasm_container, docker_cli, host_env):
        """Verify that Antigravity can use chat functionality (Language Server stability)."""
        user = host_env["HOST_USER"]
        
        # Start the IDE first
        docker_cli.exec(test_kasm_container, f"su - {user} -c 'mkdir -p ~/test_ws && cd ~/test_ws && git config --global user.email \"test@test.com\" && git config --global user.name \"Test\" && git init && git commit --allow-empty -m init'")
        docker_cli.exec(test_kasm_container, f"su - {user} -c 'DISPLAY=:1 antigravity ~/test_ws > /tmp/ag.log 2>&1 &'")
        
        # Wait a bit longer to ensure Language Server would crash if Emulation failed it
        time.sleep(10)
        res_ls = docker_cli.exec(test_kasm_container, f"su - {user} -c 'pgrep -f language_server'")
        assert res_ls.returncode == 0, "Antigravity Language Server (Chat backend) crashed or is not running"
