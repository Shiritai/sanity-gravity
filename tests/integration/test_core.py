import time

import pytest

from tests.utils import wait_for_log, wait_for_port

pytestmark = pytest.mark.requires_image("ag-xfce-ssh")


class TestCore:
    def test_core_startup(self, clean_container, docker_cli, host_env, free_port, image):
        container_name = clean_container("sanity-test-core")
        port = free_port()

        # Start Core Container
        docker_cli.run_container(
            name=container_name,
            image=image,
            ports={str(port): "22"},
            env=host_env
        )

        assert wait_for_log(container_name, "supervisord started")
        assert wait_for_port(port)

    def test_core_user_mapping(self, clean_container, docker_cli, host_env, image):
        container_name = clean_container("sanity-test-core-user")

        docker_cli.run_container(
            name=container_name,
            image=image,
            env=host_env
        )
        # Wait for startup
        time.sleep(2)

        # Check UID/GID
        uid_check = docker_cli.exec(container_name, f"id -u {host_env['HOST_USER']}").stdout.strip()
        gid_check = docker_cli.exec(container_name, f"id -g {host_env['HOST_USER']}").stdout.strip()

        assert uid_check == host_env["HOST_UID"]
        assert gid_check == host_env["HOST_GID"]

    def test_core_chrome_installation(self, clean_container, docker_cli, host_env, image):
        container_name = clean_container("sanity-test-core-chrome")
        docker_cli.run_container(name=container_name, image=image, env=host_env)

        chrome_ver = docker_cli.exec(container_name, "google-chrome --version").stdout
        assert "Google Chrome" in chrome_ver or "Chromium" in chrome_ver

    def test_core_ssh_connectivity(self, clean_container, docker_cli, host_env, free_port, image):
        # reuse or new? New for isolation
        container_name = clean_container("sanity-test-core-ssh")
        port = free_port()
        docker_cli.run_container(
            name=container_name,
            image=image,
            ports={str(port): "22"},
            env=host_env
        )
        assert wait_for_port(port)

        # Verify SSH banner or logic (using netcat in a real scenario, but simple port check is okay for basic)
        # Or checking logs for sshd
        assert wait_for_log(container_name, "sshd entered RUNNING state")
