import pytest
import subprocess
import os
import time
import socket

# Global Constants
DEFAULT_CORE_IMAGE = "sanity-gravity:core"
DEFAULT_KASM_IMAGE = "sanity-gravity:kasm"
DEFAULT_VNC_IMAGE = "sanity-gravity:vnc"

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
