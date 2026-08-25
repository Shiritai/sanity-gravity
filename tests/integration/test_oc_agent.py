"""Integration tests for the ``oc`` (OpenCode CLI) agent image.

The agent slug is the 2-char ``oc``; the installed binary is
``opencode``. Spins up the real ``sanity-gravity:oc-none-ssh`` container
and asserts the OpenCode CLI is installed and runnable by the non-root
sandbox user. OpenCode's installer stages a single Bun-compiled binary
under the root-only ``/root/.opencode``; the plugin copies it onto
``/usr/local/bin``, and these tests are the regression guard for that
world-executable install (the build itself never runs the binary --
Bun executables are unreliable under qemu cross-builds).

Skipped automatically when the image has not been built locally
(``./sanity-cli build oc-none-ssh``); CI builds it before running.
"""
import time

import pytest

from tests.utils import wait_for_log, wait_for_port

pytestmark = pytest.mark.requires_image("oc-none-ssh")


class TestOpenCodeCLIAgent:
    """Integration tests for oc (OpenCode CLI) agent containers."""

    def test_oc_startup(self, clean_container, docker_cli, host_env, free_port, image):
        container_name = clean_container("sanity-test-oc-startup")
        port = free_port()

        docker_cli.run_container(
            name=container_name,
            image=image,
            ports={str(port): "22"},
            env=host_env,
        )

        assert wait_for_log(container_name, "supervisord started")
        assert wait_for_port(port)

    def test_oc_binary_exists(self, clean_container, docker_cli, host_env, image):
        """OpenCode ships as a standalone Bun binary (no Node.js required)."""
        container_name = clean_container("sanity-test-oc-binary")
        docker_cli.run_container(name=container_name, image=image, env=host_env)
        time.sleep(2)

        result = docker_cli.exec(container_name, "which opencode")
        assert "/opencode" in result.stdout.strip()

    def test_oc_opencode_installed(self, clean_container, docker_cli, host_env, image):
        container_name = clean_container("sanity-test-oc-version")
        docker_cli.run_container(name=container_name, image=image, env=host_env)
        time.sleep(2)

        result = docker_cli.exec(container_name, "opencode --version")
        version = result.stdout.strip()
        assert version, "opencode --version returned empty"
        # e.g. "1.17.15" -- a bare semver, no product prefix
        assert version[0].isdigit(), f"Unexpected version output: {version}"

    def test_oc_user_mapping(self, clean_container, docker_cli, host_env, image):
        container_name = clean_container("sanity-test-oc-user")
        docker_cli.run_container(name=container_name, image=image, env=host_env)
        time.sleep(2)

        uid = docker_cli.exec(container_name, f"id -u {host_env['HOST_USER']}").stdout.strip()
        gid = docker_cli.exec(container_name, f"id -g {host_env['HOST_USER']}").stdout.strip()
        assert uid == host_env["HOST_UID"]
        assert gid == host_env["HOST_GID"]

    def test_oc_opencode_accessible_as_user(self, clean_container, docker_cli, host_env, image):
        """opencode must be executable by the non-root user, not just root.

        Regression guard: the upstream installer stages everything under
        /root/.opencode (mode 700); only the copy onto /usr/local/bin
        makes the binary reachable for the sandbox user.
        """
        container_name = clean_container("sanity-test-oc-user-exec")
        docker_cli.run_container(name=container_name, image=image, env=host_env)
        time.sleep(2)

        result = docker_cli.exec(
            container_name, "opencode --version", user=host_env["HOST_USER"]
        )
        version = result.stdout.strip()
        assert version, "opencode --version returned empty as non-root user"
        assert version[0].isdigit(), f"Unexpected version output: {version}"

    def test_oc_headless_no_display(self, clean_container, docker_cli, host_env, image):
        """oc-none-ssh should have DISPLAY unset (headless)."""
        container_name = clean_container("sanity-test-oc-headless")
        docker_cli.run_container(name=container_name, image=image, env=host_env)
        time.sleep(2)

        result = docker_cli.exec(
            container_name, "printenv DISPLAY", user=host_env["HOST_USER"]
        )
        assert result.stdout.strip() == "", (
            f"DISPLAY should be empty in headless mode, got: {result.stdout.strip()}"
        )
