import pytest
from tests.conftest import DEFAULT_SSH_IMAGE

class TestChrome:
    def test_chrome_launch(self, clean_container, docker_cli, host_env):
        """
        Verify that Google Chrome can launch in headless mode within the container.
        This ensures that necessary environment requirements (DBus, machine-id) are met.
        """
        container_name = clean_container("sanity-test-chrome")
        
        # We run the container with a specific command overlapping the default CMD.
        # However, entrypoint.sh uses `exec "$@"` so passing the chrome command 
        # as arguments to `docker run` will let entrypoint.sh set up the environment
        # (machine-id, dbus) and then execute chrome.
        
        env_flags = " ".join([f"-e {k}='{v}'" for k, v in host_env.items()])
        
        cmd = (
            f"docker run --name {container_name} --rm "
            f"{env_flags} "
            f"--shm-size=512m "
            f"{DEFAULT_SSH_IMAGE} "
            f"google-chrome --headless --dump-dom --disable-gpu http://example.com"
        )
        
        result = docker_cli.run(cmd)
        
        # 1. Verify exit code is 0 (success)
        assert result.returncode == 0, f"Chrome failed to launch. Stderr: {result.stderr}"
        
        # 2. Verify output content
        # Chrome might print some DBus errors to stderr even on success in headless, 
        # so we focus on stdout having the expected DOM.
        assert "Example Domain" in result.stdout, "Chrome did not return expected DOM content"
        assert "</html>" in result.stdout
