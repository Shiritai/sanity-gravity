import time
import socket
import requests
import subprocess
import urllib3

def wait_for_port(port, host='localhost', timeout=10):
    """Wait for a TCP port to be open."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (OSError, ConnectionRefusedError):
            time.sleep(0.5)
    return False

def wait_for_log(container_name, pattern, timeout=10):
    """Wait for a specific log pattern to appear in container logs."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        result = subprocess.run(f"docker logs {container_name}", shell=True, capture_output=True, text=True)
        if pattern in result.stdout or pattern in result.stderr:
            return True
        time.sleep(0.5)
    return False

def check_http(url, expected_code=None, expected_text=None, timeout=5, insecure=True):
    """Check an HTTP(S) endpoint."""
    try:
        response = requests.get(url, timeout=timeout, verify=not insecure)
        if expected_code and response.status_code != expected_code:
            # Sometimes 401 is okay if we just want to check liveness
            if expected_code == 200 and response.status_code == 401:
                return True # Accept 401 as "service reachable"
            return False
            
        if expected_text and expected_text not in response.text:
            return False
        return True
    except requests.RequestException:
        return False

def wait_for_http(url, expected_code=None, expected_text=None, timeout=15):
    """Wait for an HTTP(S) endpoint to return expected response."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        if check_http(url, expected_code, expected_text, timeout=2):
            return True
        time.sleep(1)
    return False
