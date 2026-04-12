import pytest
import subprocess
import os
import time
import socket
import contextlib

# Global Constants — Dimension-based tags
DEFAULT_SSH_IMAGE = "sanity-gravity:ag-xfce-ssh"
DEFAULT_KASM_IMAGE = "sanity-gravity:ag-xfce-kasm"
DEFAULT_VNC_IMAGE = "sanity-gravity:ag-xfce-vnc"

# Headless CLI agent images
GC_SSH_IMAGE = "sanity-gravity:gc-none-ssh"
CC_SSH_IMAGE = "sanity-gravity:cc-none-ssh"

@pytest.fixture
def free_port():
    """Fixture to find a free port."""
    def _find():
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.bind(('', 0))
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            return s.getsockname()[1]
    return _find


@pytest.fixture(scope="session")
def host_env():
    """Returns a dictionary of host environment variables required for containers."""
    # Mimic sanity-cli logic or use what's likely on host
    # Ideally should query `id -u` etc, but we can assume standard test env or use python
    uid = str(os.getuid())
    gid = str(os.getgid())
    username = os.getenv("USER", "testuser")
    
    return {
        "HOST_UID": uid,
        "HOST_GID": gid,
        "HOST_USER": username,
        "HOST_PASSWORD": "testpassword",  # Standard test password
    }

@pytest.fixture(scope="function")
def docker_cli():
    """Helper to run docker commands."""
    class DockerCLI:
        def run(self, cmd, check=True):
            print(f"DEBUG: Running docker command: {cmd}")
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if check and result.returncode != 0:
                raise RuntimeError(f"Docker command failed: {cmd}\nStderr: {result.stderr}")
            return result
            
        def run_container(self, name, image, ports=None, env=None, detatch=True, rm=True):
            cmd = f"docker run --name {name}"
            if detatch:
                cmd += " -d"
            if rm:
                cmd += " --rm"
            
            if ports:
                for host, container in ports.items():
                    cmd += f" -p {host}:{container}"
            
            if env:
                for k, v in env.items():
                    cmd += f" -e {k}='{v}'"
            
            cmd += f" --shm-size=512m {image}"
            return self.run(cmd)

        def stop(self, name):
            self.run(f"docker rm -f {name}", check=False)

        def exec(self, name, cmd, user=None):
            user_flag = f"-u {user}" if user else ""
            return self.run(f"docker exec {user_flag} {name} {cmd}")

    return DockerCLI()

@pytest.fixture(scope="function")
def clean_container(docker_cli):
    """Factory to register containers for cleanup."""
    containers = []
    
    def _register(name):
        containers.append(name)
        # Ensure it's clean before start
        docker_cli.stop(name)
        return name

    yield _register

    for name in containers:
        print(f"Cleaning up container: {name}")
        docker_cli.stop(name)
