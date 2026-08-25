"""Live counterpart of the unit-level volume-isolation tests: two tags
in one project write to their own homes and must never see each other's
data. The compose-level declarations are pinned in
``tests/unit/test_volume_isolation.py``; this boots the real thing.
"""
import getpass
import os
import subprocess
import time

import pytest

pytestmark = pytest.mark.requires_image("ag-xfce-kasm", "ag-xfce-ssh")


def test_volume_isolation_runtime(tmpdir):
    """Run two agents in the SAME project and verify they do not
    overwrite each other's home volume files."""
    username = getpass.getuser()
    project_name = "test-iso-runtime"
    workspace = os.path.join(str(tmpdir), "workspace")
    os.makedirs(workspace, exist_ok=True)

    def run_cli(args):
        return subprocess.run(
            f"./sanity-cli {args}", shell=True,
            capture_output=True, text=True, check=True,
        )

    def docker(cmd, capture=False):
        return subprocess.run(
            cmd, shell=True, capture_output=capture, text=True, check=True,
        )

    try:
        # Two tags, one project: distinct sg-<project>-<tag> volumes.
        run_cli(f"up -v ag-xfce-kasm -n {project_name} -w {workspace} --skip-check")
        run_cli(f"up -v ag-xfce-ssh -n {project_name} -w {workspace} --skip-check")

        kasm_container = f"{project_name}-ag-xfce-kasm-1"
        ssh_container = f"{project_name}-ag-xfce-ssh-1"

        # Wait for containers to be ready.
        time.sleep(3)

        docker(
            f"docker exec {kasm_container} sh -c "
            f"'echo KASM_DATA > /home/{username}/isolation.txt'"
        )
        docker(
            f"docker exec {ssh_container} sh -c "
            f"'echo SSH_DATA > /home/{username}/isolation.txt'"
        )

        kasm_read = docker(
            f"docker exec {kasm_container} cat /home/{username}/isolation.txt",
            capture=True,
        ).stdout.strip()
        ssh_read = docker(
            f"docker exec {ssh_container} cat /home/{username}/isolation.txt",
            capture=True,
        ).stdout.strip()

        assert kasm_read == "KASM_DATA", (
            f"Isolation failed! Expected KASM_DATA but got {kasm_read}"
        )
        assert ssh_read == "SSH_DATA", (
            f"Isolation failed! Expected SSH_DATA but got {ssh_read}"
        )
    finally:
        run_cli(f"down -n {project_name}")
