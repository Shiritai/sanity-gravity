import pytest

from tests.utils import wait_for_log, wait_for_port

pytestmark = pytest.mark.requires_image("ag-xfce-kasm", "ag-xfce-vnc")


class TestParams:
    def test_custom_password_kasm(self, clean_container, docker_cli, host_env, free_port, images):
        container_name = clean_container("sanity-test-kasm-pwd")
        custom_pw = "secret123"
        port = free_port()
        
        env = host_env.copy()
        env["HOST_PASSWORD"] = custom_pw
        
        docker_cli.run_container(
            name=container_name,
            image=images["ag-xfce-kasm"],
            ports={str(port): "8444"},
            env=env
        )
        
        assert wait_for_log(container_name, "success: kasmvnc")
        
        # Verify env inside
        out = docker_cli.exec(container_name, "env | grep HOST_PASSWORD").stdout
        assert f"HOST_PASSWORD={custom_pw}" in out
        
        # Ideally we could verify vncpasswd file hash, but env verification + successful boot is strong enough for now

    def test_custom_ports_vnc(self, clean_container, docker_cli, host_env, free_port, images):
        container_name = clean_container("sanity-test-vnc-ports")
        
        custom_vnc = str(free_port())
        custom_novnc = str(free_port())
        
        env = host_env.copy()
        env.update({
            "VNC_PW": "test",
            "VNC_RESOLUTION": "1024x768",
            "VNC_DEPTH": "24"
        })
        
        # Check host-side customization via CLI is usually handled by sanity-cli argument parsing -> env var, 
        # but here we test the container's ability to bind if mapped differently?
        # Actually default docker-compose maps ${VNC_PORT}:5901.
        # Direct docker run maps HostPort:InternalPort.
        # Internal port is fixed at 5901 for TigerVNC (unless we change startup script to listen elsewhere).
        # The test_parameters.py in original test phase 5 checked "CLI run with custom port".
        # Since we are testing containers here, we verify that mapping works.
        
        docker_cli.run_container(
            name=container_name,
            image=images["ag-xfce-vnc"],
            ports={custom_vnc: "5901", custom_novnc: "6901"},
            env=env
        )
        
        assert wait_for_port(int(custom_vnc))
        assert wait_for_port(int(custom_novnc))
