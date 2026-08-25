"""Integration tests for the ``cx`` (OpenAI Codex CLI) agent image.

The agent slug is the 2-char ``cx``; the installed binary is still
``codex``. Spins up the real ``sanity-gravity:cx-none-ssh`` container and
asserts the Codex CLI is installed and -- crucially -- runnable by the
non-root sandbox user. Codex's installer only drops a symlink into the
install dir while the real binary lives under ``$HOME/.codex``; left at
the default ``$HOME=/root`` (mode 700) that symlink dangles for every
non-root user, so this is the regression guard for the plugin's
world-readable ``/opt`` install.

Skipped automatically when the image has not been built locally
(``./sanity-cli build cx-none-ssh``); CI builds it before running.
"""
import time

import pytest

from tests.utils import wait_for_log, wait_for_port

pytestmark = pytest.mark.requires_image("cx-none-ssh")


class TestCodexCLIAgent:
    """Integration tests for cx (OpenAI Codex CLI) agent containers."""

    def test_cx_startup(self, clean_container, docker_cli, host_env, free_port, image):
        container_name = clean_container("sanity-test-cx-startup")
        port = free_port()

        docker_cli.run_container(
            name=container_name,
            image=image,
            ports={str(port): "22"},
            env=host_env,
        )

        assert wait_for_log(container_name, "supervisord started")
        assert wait_for_port(port)

    def test_cx_binary_exists(self, clean_container, docker_cli, host_env, image):
        """Codex ships as a standalone musl binary (no Node.js required)."""
        container_name = clean_container("sanity-test-cx-binary")
        docker_cli.run_container(name=container_name, image=image, env=host_env)
        time.sleep(2)

        result = docker_cli.exec(container_name, "which codex")
        assert "/codex" in result.stdout.strip()

    def test_cx_codex_installed(self, clean_container, docker_cli, host_env, image):
        container_name = clean_container("sanity-test-cx-version")
        docker_cli.run_container(name=container_name, image=image, env=host_env)
        time.sleep(2)

        result = docker_cli.exec(container_name, "codex --version")
        version = result.stdout.strip()
        assert version, "codex --version returned empty"
        # e.g. "codex-cli 0.142.0"
        assert "codex" in version.lower(), f"Unexpected version output: {version}"

    def test_cx_user_mapping(self, clean_container, docker_cli, host_env, image):
        container_name = clean_container("sanity-test-cx-user")
        docker_cli.run_container(name=container_name, image=image, env=host_env)
        time.sleep(2)

        uid = docker_cli.exec(container_name, f"id -u {host_env['HOST_USER']}").stdout.strip()
        gid = docker_cli.exec(container_name, f"id -g {host_env['HOST_USER']}").stdout.strip()
        assert uid == host_env["HOST_UID"]
        assert gid == host_env["HOST_GID"]

    def test_cx_codex_accessible_as_user(self, clean_container, docker_cli, host_env, image):
        """codex must be executable by the non-root user, not just root.

        Regression guard: the upstream installer symlinks into $HOME/.codex,
        which is unreadable to non-root users when HOME=/root (mode 700).
        """
        container_name = clean_container("sanity-test-cx-user-exec")
        docker_cli.run_container(name=container_name, image=image, env=host_env)
        time.sleep(2)

        result = docker_cli.exec(
            container_name, "codex --version", user=host_env["HOST_USER"]
        )
        version = result.stdout.strip()
        assert version, "codex --version returned empty as non-root user"
        assert "codex" in version.lower(), f"Unexpected version output: {version}"

    def test_cx_headless_no_display(self, clean_container, docker_cli, host_env, image):
        """cx-none-ssh should have DISPLAY unset (headless)."""
        container_name = clean_container("sanity-test-cx-headless")
        docker_cli.run_container(name=container_name, image=image, env=host_env)
        time.sleep(2)

        result = docker_cli.exec(
            container_name, "printenv DISPLAY", user=host_env["HOST_USER"]
        )
        assert result.stdout.strip() == "", (
            f"DISPLAY should be empty in headless mode, got: {result.stdout.strip()}"
        )
