import os
import subprocess
import time
import pytest
import shutil

# Configuration
PROJECT_NAME = "sanity-test-integrity"
VARIANT = "ag-xfce-kasm"
IMAGE_TAG = "sanity-test:integrity"
CLI = "./sanity-cli"

def run(cmd):
    subprocess.check_call(cmd, shell=True)

def verify_cleanup_logic():
    """
    E2E Test:
    1. Start a container.
    2. 'Pollute' it with fake Agent Lock files.
    3. Restart it (which triggers startup.sh).
    4. Verify locks are gone.
    """
    print(f"--- Starting Integrity Test ({PROJECT_NAME}) ---")
    
    # Ensure clean slate
    subprocess.call(f"{CLI} down --name {PROJECT_NAME}", shell=True, stderr=subprocess.DEVNULL)
    
    try:
        # 1. Start Container
        run(f"{CLI} run -v {VARIANT} --name {PROJECT_NAME}")
        # Wait for startup
        time.sleep(5) 
        
        # 2. Pollute State (Simulate a crashed Agent)
        pollution_cmds = [
            "mkdir -p /home/archroiko/.gemini/antigravity-browser-profile/Crashpad",
            "touch /home/archroiko/.gemini/antigravity-browser-profile/SingletonLock",
            "touch /home/archroiko/.gemini/antigravity-browser-profile/SingletonSocket",
            "mkdir -p /home/archroiko/.config/google-chrome/Crashpad",
            "touch /home/archroiko/.config/google-chrome/SingletonLock"
        ]
        
        container_name = f"{PROJECT_NAME}-{VARIANT}-1"
        for pcmd in pollution_cmds:
            run(f"docker exec -u archroiko {container_name} {pcmd}")
            
        print(">>> State Polluted. Restarting container to trigger cleanup...")
        
        # 3. Restart (Triggers startup.sh)
        run(f"{CLI} restart --name {PROJECT_NAME}")
        time.sleep(5) # Wait for startup script to run
        
        # 4. Verify Cleanup
        # Check Agent Profile
        check_agent = subprocess.run(
            f"docker exec -u archroiko {container_name} ls /home/archroiko/.gemini/antigravity-browser-profile/SingletonLock",
            shell=True, capture_output=True
        )
        
        # Check System Chrome
        check_chrome = subprocess.run(
            f"docker exec -u archroiko {container_name} ls /home/archroiko/.config/google-chrome/SingletonLock",
            shell=True, capture_output=True
        )
        
        # Assertion: Both should fail (exit code non-zero) because file shouldn't exist
        errors = []
        if check_agent.returncode == 0:
            errors.append("FAILURE: Agent SingletonLock persists after restart!")
        else:
            print("SUCCESS: Agent SingletonLock removed.")
            
        if check_chrome.returncode == 0:
            errors.append("FAILURE: Chrome SingletonLock persists after restart!")
        else:
            print("SUCCESS: Chrome SingletonLock removed.")
            
        if errors:
            raise RuntimeError("\n".join(errors))
            
        print(">>> INTEGRITY TEST PASSED <<<")
            
    finally:
        # Cleanup
        subprocess.call(f"{CLI} down --name {PROJECT_NAME}", shell=True)

if __name__ == "__main__":
    verify_cleanup_logic()
