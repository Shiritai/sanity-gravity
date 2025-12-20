from tests.utils import wait_for_port, wait_for_log, check_http
from tests.conftest import DEFAULT_KASM_IMAGE

class TestKasm:
    def test_kasm_startup(self, clean_container, docker_cli, host_env):
        container_name = clean_container("sanity-test-kasm")
        
        # Start Kasm Container
        docker_cli.run_container(
            name=container_name,
            image=DEFAULT_KASM_IMAGE,
            ports={"8444": "8444"},
            env=host_env
        )
        
        assert wait_for_log(container_name, "success: kasmvnc", timeout=15)
        assert wait_for_port(8444)

    def test_kasm_http_endpoint(self, clean_container, docker_cli, host_env):
        container_name = clean_container("sanity-test-kasm-http")
        docker_cli.run_container(
            name=container_name,
            image=DEFAULT_KASM_IMAGE,
            ports={"8445": "8444"}, # Avoid port conflict if parallel
            env=host_env
        )
        
        assert wait_for_log(container_name, "success: kasmvnc", timeout=15)
        
        # Check HTTP response (HTTPS with self-signed cert)
        url = "https://localhost:8445"
        # Expect 200 or 401 (auth required), either means server is up
        assert check_http(url, timeout=5, insecure=True)

    def test_kasm_ssl_cert_group(self, clean_container, docker_cli, host_env):
        container_name = clean_container("sanity-test-kasm-ssl")
        docker_cli.run_container(name=container_name, image=DEFAULT_KASM_IMAGE, env=host_env)
        
        groups = docker_cli.exec(container_name, f"groups {host_env['HOST_USER']}").stdout
        assert "ssl-cert" in groups
