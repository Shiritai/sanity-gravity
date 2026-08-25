import pytest

from tests.utils import wait_for_http, wait_for_port

pytestmark = pytest.mark.requires_image("ag-xfce-vnc")


class TestVNC:
    def test_vnc_startup(self, clean_container, docker_cli, host_env, free_port, image):
        container_name = clean_container("sanity-test-vnc")

        # Add VNC Env Vars
        env = host_env.copy()
        env.update({
            "VNC_PW": "testpassword",
            "VNC_RESOLUTION": "1280x720",
            "VNC_DEPTH": "24"
        })

        # Start VNC Container
        # Use dynamic ports to avoid conflict
        vnc_port = free_port()
        novnc_port = free_port()

        docker_cli.run_container(
            name=container_name,
            image=image,
            ports={str(vnc_port): "5901", str(novnc_port): "6901"},
            env=env
        )

        assert wait_for_port(vnc_port, timeout=15)
        # noVNC might take longer to be served
        assert wait_for_port(novnc_port, timeout=15)

    def test_novnc_http(self, clean_container, docker_cli, host_env, free_port, image):
        container_name = clean_container("sanity-test-vnc-http")

        env = host_env.copy()
        env.update({
            "VNC_PW": "testpassword",
            "VNC_RESOLUTION": "1280x720",
            "VNC_DEPTH": "24"
        })

        novnc_port = free_port()

        docker_cli.run_container(
            name=container_name,
            image=image,
            ports={str(novnc_port): "6901"},
            env=env
        )

        assert wait_for_port(novnc_port, timeout=15)

        url = f"http://localhost:{novnc_port}/vnc.html"
        assert wait_for_http(url, expected_code=200, expected_text="noVNC", timeout=20)
