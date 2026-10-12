"""The debian base, in built images.

The other integration suites run on the default base. These boot one
headless and one IDE tag on debian: the base layer, the entrypoint's
user mapping and the distro-specific branches (kasm's deb, ag's runtime
libraries, the browser) are what a second base can break.
"""
from __future__ import annotations

import time

import pytest

from tests.utils import wait_for_log, wait_for_port


def _os_id(docker_cli, container_name) -> str:
    return docker_cli.exec(
        container_name, "sh -c '. /etc/os-release && echo $ID:$VERSION_CODENAME'"
    ).stdout.strip()


@pytest.mark.requires_image("cc-none-ssh-debian")
class TestHeadlessDebian:
    def test_boots_and_serves_ssh(
        self, clean_container, docker_cli, host_env, free_port, image,
    ):
        container_name = clean_container("sanity-test-debian-ssh")
        port = free_port()
        docker_cli.run_container(
            name=container_name, image=image, ports={str(port): "22"}, env=host_env,
        )

        assert wait_for_log(container_name, "supervisord started")
        assert wait_for_port(port)
        assert _os_id(docker_cli, container_name) == "debian:bookworm"

    def test_maps_the_host_user(self, clean_container, docker_cli, host_env, image):
        container_name = clean_container("sanity-test-debian-user")
        docker_cli.run_container(name=container_name, image=image, env=host_env)
        time.sleep(2)

        user = host_env["HOST_USER"]
        assert docker_cli.exec(container_name, f"id -u {user}").stdout.strip() == host_env["HOST_UID"]
        assert docker_cli.exec(container_name, f"id -g {user}").stdout.strip() == host_env["HOST_GID"]

    def test_the_agent_runs_as_the_user(self, clean_container, docker_cli, host_env, image):
        container_name = clean_container("sanity-test-debian-agent")
        docker_cli.run_container(name=container_name, image=image, env=host_env)
        time.sleep(2)

        result = docker_cli.exec(container_name, "claude --version", user=host_env["HOST_USER"])
        assert result.stdout.strip()[:1].isdigit(), result.stdout


@pytest.mark.requires_image("ag-xfce-kasm-debian")
class TestIdeDebian:
    def test_kasm_starts(self, clean_container, docker_cli, host_env, free_port, image):
        container_name = clean_container("sanity-test-debian-kasm")
        port = free_port()
        docker_cli.run_container(
            name=container_name, image=image, ports={str(port): "8444"}, env=host_env,
        )

        assert wait_for_log(container_name, "success: kasmvnc", timeout=15)
        assert wait_for_port(port)
        assert _os_id(docker_cli, container_name) == "debian:bookworm"

    def test_the_ide_finds_its_libraries(self, clean_container, docker_cli, host_env, image):
        """The IDE's runtime libraries are named per distro in the ag
        Dockerfile; a wrong name fails the build, a missing one only
        shows here, as an unresolved shared object."""
        container_name = clean_container("sanity-test-debian-ide-libs")
        docker_cli.run_container(name=container_name, image=image, env=host_env)
        time.sleep(2)

        result = docker_cli.exec(
            container_name, "ldd /usr/share/antigravity-ide/antigravity-ide-bin",
        )
        assert "libc.so.6" in result.stdout, result.stdout + result.stderr
        assert "not found" not in result.stdout

    def test_the_browser_is_installed(self, clean_container, docker_cli, host_env, image):
        container_name = clean_container("sanity-test-debian-browser")
        docker_cli.run_container(name=container_name, image=image, env=host_env)
        time.sleep(2)

        result = docker_cli.exec(container_name, "readlink -f /usr/bin/x-www-browser")
        assert result.stdout.strip() == "/usr/bin/google-chrome-safe"
