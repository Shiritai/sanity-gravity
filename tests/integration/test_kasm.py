import pytest

from tests.utils import wait_for_http, wait_for_log, wait_for_port

pytestmark = pytest.mark.requires_image("ag-xfce-kasm")


class TestKasm:
    def test_kasm_startup(self, clean_container, docker_cli, host_env, free_port, image):
        container_name = clean_container("sanity-test-kasm")
        port = free_port()

        # Start Kasm Container
        docker_cli.run_container(
            name=container_name,
            image=image,
            ports={str(port): "8444"},
            env=host_env
        )

        assert wait_for_log(container_name, "success: kasmvnc", timeout=15)
        assert wait_for_port(port)

    def test_kasm_http_endpoint(self, clean_container, docker_cli, host_env, free_port, image):
        container_name = clean_container("sanity-test-kasm-http")
        port = free_port()
        docker_cli.run_container(
            name=container_name,
            image=image,
            ports={str(port): "8444"}, # Avoid port conflict if parallel
            env=host_env
        )

        # Check HTTP response (HTTPS with self-signed cert)
        url = f"https://localhost:{port}"
        # Expect 200 or 401 (auth required), either means server is up
        assert wait_for_http(url, timeout=15)

    def test_kasm_ssl_cert_group(self, clean_container, docker_cli, host_env, image):
        container_name = clean_container("sanity-test-kasm-ssl")
        docker_cli.run_container(name=container_name, image=image, env=host_env)

        # Wait for entrypoint to finish and kasm to start
        assert wait_for_log(container_name, "success: kasmvnc", timeout=15)

        groups = docker_cli.exec(container_name, f"groups {host_env['HOST_USER']}").stdout
        assert "ssl-cert" in groups
