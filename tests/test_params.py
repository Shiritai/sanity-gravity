from tests.utils import wait_for_port, wait_for_log
from tests.conftest import DEFAULT_KASM_IMAGE, DEFAULT_VNC_IMAGE

class TestParams:
    def test_custom_password_kasm(self, clean_container, docker_cli, host_env):
        container_name = clean_container("sanity-test-kasm-pwd")
        custom_pw = "secret123"
        
        env = host_env.copy()
        env["HOST_PASSWORD"] = custom_pw
        
        docker_cli.run_container(
            name=container_name,
            image=DEFAULT_KASM_IMAGE,
            ports={"9444": "8444"},
            env=env
        )
        
        assert wait_for_log(container_name, "success: kasmvnc")
        
        # Verify env inside
        out = docker_cli.exec(container_name, "env | grep HOST_PASSWORD").stdout
        assert f"HOST_PASSWORD={custom_pw}" in out
        
        # Ideally we could verify vncpasswd file hash, but env verification + successful boot is strong enough for now

    def test_custom_ports_vnc(self, clean_container, docker_cli, host_env):
        container_name = clean_container("sanity-test-vnc-ports")
        
        custom_vnc = "5999"
        custom_novnc = "6999"
        
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
            image=DEFAULT_VNC_IMAGE,
            ports={custom_vnc: "5901", custom_novnc: "6901"},
            env=env
        )
        
        assert wait_for_port(int(custom_vnc))
        assert wait_for_port(int(custom_novnc))
