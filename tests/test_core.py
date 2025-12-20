import pytest
from tests.utils import wait_for_port, wait_for_log, check_http
from tests.conftest import DEFAULT_CORE_IMAGE
import time

class TestCore:
    def test_core_startup(self, clean_container, docker_cli, host_env):
        container_name = clean_container("sanity-test-core")
        
        # Start Core Container
        docker_cli.run_container(
            name=container_name,
            image=DEFAULT_CORE_IMAGE,
            ports={"2222": "22"},
            env=host_env
        )
        
        assert wait_for_log(container_name, "supervisord started")
        assert wait_for_port(2222)

    def test_core_user_mapping(self, clean_container, docker_cli, host_env):
        container_name = clean_container("sanity-test-core-user")
        
        docker_cli.run_container(
            name=container_name,
            image=DEFAULT_CORE_IMAGE,
            env=host_env
        )
        # Wait for startup
        time.sleep(2)
        
        # Check UID/GID
        uid_check = docker_cli.exec(container_name, f"id -u {host_env['HOST_USER']}").stdout.strip()
        gid_check = docker_cli.exec(container_name, f"id -g {host_env['HOST_USER']}").stdout.strip()
        
        assert uid_check == host_env["HOST_UID"]
        assert gid_check == host_env["HOST_GID"]

    def test_core_chrome_installation(self, clean_container, docker_cli, host_env):
        container_name = clean_container("sanity-test-core-chrome")
        docker_cli.run_container(name=container_name, image=DEFAULT_CORE_IMAGE, env=host_env)
        
        chrome_ver = docker_cli.exec(container_name, "google-chrome --version").stdout
        assert "Google Chrome" in chrome_ver

    def test_core_ssh_connectivity(self, clean_container, docker_cli, host_env):
        # reuse or new? New for isolation
        container_name = clean_container("sanity-test-core-ssh")
        docker_cli.run_container(
            name=container_name,
            image=DEFAULT_CORE_IMAGE,
            ports={"2222": "22"},
            env=host_env
        )
        assert wait_for_port(2222)
        
        # Verify SSH banner or logic (using netcat in a real scenario, but simple port check is okay for basic)
        # Or checking logs for sshd
        assert wait_for_log(container_name, "sshd entered RUNNING state")
