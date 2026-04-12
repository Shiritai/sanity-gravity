import pytest
import time
from tests.utils import wait_for_port, wait_for_log
from tests.conftest import GC_SSH_IMAGE, CC_SSH_IMAGE


class TestGeminiCLIAgent:
    """Integration tests for gc (Gemini CLI) agent containers."""

    def test_gc_startup(self, clean_container, docker_cli, host_env, free_port):
        container_name = clean_container("sanity-test-gc-startup")
        port = free_port()

        docker_cli.run_container(
            name=container_name,
            image=GC_SSH_IMAGE,
            ports={str(port): "22"},
            env=host_env,
        )

        assert wait_for_log(container_name, "supervisord started")
        assert wait_for_port(port)

    def test_gc_node_installed(self, clean_container, docker_cli, host_env):
        container_name = clean_container("sanity-test-gc-node")
        docker_cli.run_container(name=container_name, image=GC_SSH_IMAGE, env=host_env)
        time.sleep(2)

        result = docker_cli.exec(container_name, "node --version")
        assert result.stdout.strip().startswith("v")

    def test_gc_gemini_installed(self, clean_container, docker_cli, host_env):
        container_name = clean_container("sanity-test-gc-gemini")
        docker_cli.run_container(name=container_name, image=GC_SSH_IMAGE, env=host_env)
        time.sleep(2)

        result = docker_cli.exec(container_name, "gemini --version")
        # Should output a version string like "0.37.1"
        version = result.stdout.strip()
        assert version, "gemini --version returned empty"
        assert version[0].isdigit(), f"Unexpected version output: {version}"

    def test_gc_user_mapping(self, clean_container, docker_cli, host_env):
        container_name = clean_container("sanity-test-gc-user")
        docker_cli.run_container(name=container_name, image=GC_SSH_IMAGE, env=host_env)
        time.sleep(2)

        uid = docker_cli.exec(container_name, f"id -u {host_env['HOST_USER']}").stdout.strip()
        gid = docker_cli.exec(container_name, f"id -g {host_env['HOST_USER']}").stdout.strip()
        assert uid == host_env["HOST_UID"]
        assert gid == host_env["HOST_GID"]

    def test_gc_headless_no_display(self, clean_container, docker_cli, host_env):
        """gc-none-ssh should have DISPLAY unset (headless)."""
        container_name = clean_container("sanity-test-gc-headless")
        docker_cli.run_container(name=container_name, image=GC_SSH_IMAGE, env=host_env)
        time.sleep(2)

        result = docker_cli.exec(container_name, "printenv DISPLAY", user=host_env["HOST_USER"])
        # DISPLAY should be empty or unset
        assert result.stdout.strip() == "", f"DISPLAY should be empty in headless mode, got: {result.stdout.strip()}"


class TestClaudeCodeAgent:
    """Integration tests for cc (Claude Code) agent containers."""

    def test_cc_startup(self, clean_container, docker_cli, host_env, free_port):
        container_name = clean_container("sanity-test-cc-startup")
        port = free_port()

        docker_cli.run_container(
            name=container_name,
            image=CC_SSH_IMAGE,
            ports={str(port): "22"},
            env=host_env,
        )

        assert wait_for_log(container_name, "supervisord started")
        assert wait_for_port(port)

    def test_cc_claude_binary_exists(self, clean_container, docker_cli, host_env):
        """Claude Code uses official installer (standalone binary, no Node.js required)."""
        container_name = clean_container("sanity-test-cc-binary")
        docker_cli.run_container(name=container_name, image=CC_SSH_IMAGE, env=host_env)
        time.sleep(2)

        result = docker_cli.exec(container_name, "which claude")
        assert "/claude" in result.stdout.strip()

    def test_cc_claude_installed(self, clean_container, docker_cli, host_env):
        container_name = clean_container("sanity-test-cc-claude")
        docker_cli.run_container(name=container_name, image=CC_SSH_IMAGE, env=host_env)
        time.sleep(2)

        result = docker_cli.exec(container_name, "claude --version")
        version = result.stdout.strip()
        assert version, "claude --version returned empty"
        assert "Claude Code" in version or version[0].isdigit(), f"Unexpected version output: {version}"

    def test_cc_user_mapping(self, clean_container, docker_cli, host_env):
        container_name = clean_container("sanity-test-cc-user")
        docker_cli.run_container(name=container_name, image=CC_SSH_IMAGE, env=host_env)
        time.sleep(2)

        uid = docker_cli.exec(container_name, f"id -u {host_env['HOST_USER']}").stdout.strip()
        gid = docker_cli.exec(container_name, f"id -g {host_env['HOST_USER']}").stdout.strip()
        assert uid == host_env["HOST_UID"]
        assert gid == host_env["HOST_GID"]

    def test_cc_headless_no_display(self, clean_container, docker_cli, host_env):
        """cc-none-ssh should have DISPLAY unset (headless)."""
        container_name = clean_container("sanity-test-cc-headless")
        docker_cli.run_container(name=container_name, image=CC_SSH_IMAGE, env=host_env)
        time.sleep(2)

        result = docker_cli.exec(container_name, "printenv DISPLAY", user=host_env["HOST_USER"])
        assert result.stdout.strip() == "", f"DISPLAY should be empty in headless mode, got: {result.stdout.strip()}"
