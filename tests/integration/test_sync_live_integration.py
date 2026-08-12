
import os
import subprocess
import tempfile

import pytest


from sanity_gravity.verbs.sync import sync_config

TEST_CONTAINER_NAME = "sanity-test-sync-live"
TEST_USER = "testuser"
TEST_UID = "1001"

def run_cmd(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

@pytest.fixture(scope="module")
def setup_test_container():
    # Setup: Start a lightweight container (alpine or debian)
    # Ensure it has basic tools. Debian/Ubuntu is safer for useradd.
    print(f"Starting test container {TEST_CONTAINER_NAME}...")
    run_cmd(f"docker rm -f {TEST_CONTAINER_NAME}")
    
    # Use busybox or alpine? Ubuntu is heavy but reliable for useradd. 
    # Let's use sanity-gravity-core image if available to be closest to prod, 
    # but fallback to ubuntu:latest.
    # Actually, let's use ubuntu:latest to imply standalone verification.
    res = run_cmd(f"docker run -d --name {TEST_CONTAINER_NAME} ubuntu:latest tail -f /dev/null")
    if res.returncode != 0:
        pytest.fail(f"Failed to start container: {res.stderr}")

    # Create a user inside
    print("Creating test user...")
    run_cmd(f"docker exec {TEST_CONTAINER_NAME} useradd -u {TEST_UID} -m {TEST_USER}")
    
    yield
    
    # Teardown
    print(f"Removing test container {TEST_CONTAINER_NAME}...")
    run_cmd(f"docker rm -f {TEST_CONTAINER_NAME}")

def test_sync_config_live_execution(setup_test_container):
    """Verifies that sync_config actually copies files and sets permissions."""
    
    with tempfile.TemporaryDirectory() as temp_config_dir:
        # 1. Prepare Source Config
        gemini_md = os.path.join(temp_config_dir, "GEMINI.md")
        settings_json = os.path.join(temp_config_dir, "settings.json")
        
        with open(gemini_md, "w") as f:
            f.write("# Live Verification Test\nSuccess")
        with open(settings_json, "w") as f:
            f.write('{"verified": true}')
            
        # 2. Execute sync_config
        print("\nExecuting sync_config...")
        # Note: We pass project_name="test-proj" but it's unused by the core logic except for logging
        sync_config("test-proj", TEST_CONTAINER_NAME, TEST_USER, config_source=temp_config_dir)
        
        # 3. Verify Files Existence
        target_dir = f"/home/{TEST_USER}/.gemini"
        
        # Check GEMINI.md
        cmd = f"docker exec {TEST_CONTAINER_NAME} cat {target_dir}/GEMINI.md"
        res = run_cmd(cmd)
        assert res.returncode == 0, f"Failed to read GEMINI.md: {res.stderr}"
        assert "# Live Verification Test" in res.stdout
        
        # Check settings.json
        cmd = f"docker exec {TEST_CONTAINER_NAME} cat {target_dir}/settings.json"
        res = run_cmd(cmd)
        assert res.returncode == 0
        assert '{"verified": true}' in res.stdout
        
        # 4. Verify Permissions
        # Check owner of the directory
        cmd = f"docker exec {TEST_CONTAINER_NAME} stat -c '%u' {target_dir}"
        res = run_cmd(cmd)
        assert res.stdout.strip() == TEST_UID, f"Directory owner UID mismatch. Expected {TEST_UID}, got {res.stdout.strip()}"
        
        # Check owner of the file
        cmd = f"docker exec {TEST_CONTAINER_NAME} stat -c '%u' {target_dir}/GEMINI.md"
        res = run_cmd(cmd)
        assert res.stdout.strip() == TEST_UID, f"File owner UID mismatch. Expected {TEST_UID}, got {res.stdout.strip()}"
