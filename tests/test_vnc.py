from tests.utils import wait_for_port, wait_for_log, check_http, wait_for_http
from tests.conftest import DEFAULT_VNC_IMAGE

class TestVNC:
    def test_vnc_startup(self, clean_container, docker_cli, host_env):
        container_name = clean_container("sanity-test-vnc")
        
        # Add VNC Env Vars
        env = host_env.copy()
        env.update({
            "VNC_PW": "testpassword",
            "VNC_RESOLUTION": "1280x720",
            "VNC_DEPTH": "24"
        })
        
        # Start VNC Container
        # Use offset ports to avoid conflict with defaults/other tests
        vnc_port = "5920"
        novnc_port = "6920"
        
        docker_cli.run_container(
            name=container_name,
            image=DEFAULT_VNC_IMAGE,
            ports={vnc_port: "5901", novnc_port: "6901"},
            env=env
        )
        
        assert wait_for_port(int(vnc_port), timeout=15)
        # noVNC might take longer to be served
        assert wait_for_port(int(novnc_port), timeout=15)

    def test_novnc_http(self, clean_container, docker_cli, host_env):
        container_name = clean_container("sanity-test-vnc-http")
        
        env = host_env.copy()
        env.update({
            "VNC_PW": "testpassword",
            "VNC_RESOLUTION": "1280x720",
            "VNC_DEPTH": "24"
        })
        
        novnc_port = "6921"
        
        docker_cli.run_container(
            name=container_name,
            image=DEFAULT_VNC_IMAGE,
            ports={novnc_port: "6901"}, 
            env=env
        )
        
        assert wait_for_port(int(novnc_port), timeout=15)
        
        
        url = f"http://localhost:{novnc_port}/vnc.html"
        assert wait_for_http(url, expected_code=200, expected_text="noVNC", timeout=20)
