"""Integration tests for the ``dsh`` (DeepSeek Harness) agent image.

Spins up the real ``sanity-gravity:dsh-none-ssh`` container and asserts
the harness launcher is installed and runnable by the non-root sandbox
user. The layer installs the hash-pinned runtime wheel into a root-owned
venv and fronts it with a /usr/local/bin/dsh wrapper that defaults
DSH_HOME and DSH_TELEMETRY_MODE for every entry path (ssh sessions get a
fresh PAM environment, so Dockerfile ENV alone would not reach them) --
these tests are the regression guard for that wrapper.

Community tier: skipped automatically when the image has not been built
locally (``./sanity-cli build dsh-none-ssh``), and CI never builds it,
so the skip stays truthful there too.
"""
import time

import pytest

from tests.utils import wait_for_log, wait_for_port

pytestmark = pytest.mark.requires_image("dsh-none-ssh")


class TestDeepSeekHarnessAgent:
    """Integration tests for dsh (DeepSeek Harness) agent containers."""

    def test_dsh_startup(self, clean_container, docker_cli, host_env, free_port, image):
        container_name = clean_container("sanity-test-dsh-startup")
        port = free_port()

        docker_cli.run_container(
            name=container_name,
            image=image,
            ports={str(port): "22"},
            env=host_env,
        )

        assert wait_for_log(container_name, "supervisord started")
        assert wait_for_port(port)

    def test_dsh_binary_exists(self, clean_container, docker_cli, host_env, image):
        container_name = clean_container("sanity-test-dsh-binary")
        docker_cli.run_container(name=container_name, image=image, env=host_env)
        time.sleep(2)

        result = docker_cli.exec(container_name, "which dsh")
        assert "/dsh" in result.stdout.strip()

    def test_dsh_version_runs_as_user(self, clean_container, docker_cli, host_env, image):
        """The pinned rc must at least self-report; a broken wheel or a
        wrapper that loses DSH_HOME fails here, not at first real use."""
        container_name = clean_container("sanity-test-dsh-version")
        docker_cli.run_container(name=container_name, image=image, env=host_env)
        time.sleep(2)

        result = docker_cli.exec(
            container_name, "dsh --version", user=host_env["HOST_USER"],
        )
        version = result.stdout.strip()
        assert version, "dsh --version returned empty"
        assert "0.1.5" in version, f"unexpected version output: {version}"

    def test_dsh_home_and_patch_seeded_under_user_home(
        self, clean_container, docker_cli, host_env, image,
    ):
        """The wheel-packaged dsh refuses to run without a non-empty
        DSH_HOME (the wrapper defaults it under $HOME so state rides the
        home-volume / config-sync story), and the entrypoint hook must
        seed the patch layer that keeps the pinned rc wheel bootable."""
        container_name = clean_container("sanity-test-dsh-home")
        docker_cli.run_container(name=container_name, image=image, env=host_env)
        time.sleep(2)

        result = docker_cli.exec(
            container_name,
            "sh -c 'ls -d \"$HOME/.dsh\"; grep -c session-title-llm \"$HOME/.dsh/cordis.patch.yml\"'",
            user=host_env["HOST_USER"],
        )
        assert "/.dsh" in result.stdout
        assert "1" in result.stdout

    def test_dsh_headless_without_key_fails_cleanly(
        self, clean_container, docker_cli, host_env, image,
    ):
        """Both profiles must boot on the pinned rc. Headless with no
        API key has to reach dsh's own credential check and report
        MISSING_CREDENTIAL - a module-resolution crash before that
        point means the patch-layer workaround regressed."""
        container_name = clean_container("sanity-test-dsh-headless")
        docker_cli.run_container(name=container_name, image=image, env=host_env)
        time.sleep(2)

        result = docker_cli.exec(
            container_name,
            "sh -c 'unset DEEPSEEK_API_KEY; dsh --profile headless hi 2>&1; true'",
            user=host_env["HOST_USER"],
        )
        assert "MISSING_CREDENTIAL" in result.stdout
        assert "DEEPSEEK_API_KEY" in result.stdout
