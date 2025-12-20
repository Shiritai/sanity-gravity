import unittest
import subprocess
import time
import os
import requests
import socket

class TestSandboxPhase1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print("\n[Setup] Cleaning up old containers...")
        subprocess.run("docker rm -f sandbox-test-core sandbox-test-kasm", shell=True, stderr=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):
        print("\n[Teardown] Cleaning up containers...")
        subprocess.run("docker rm -f sandbox-test-core sandbox-test-kasm", shell=True, stderr=subprocess.DEVNULL)

    def run_command(self, cmd):
        return subprocess.run(cmd, shell=True, capture_output=True, text=True)

    def test_01_build_core(self):
        print("\n[Test] Building Core Image...")
        result = self.run_command("docker build -t sanity-gravity:core -f sandbox/variants/core/Dockerfile sandbox")
        self.assertEqual(result.returncode, 0, f"Core build failed: {result.stderr}")

    def test_02_build_kasm(self):
        print("\n[Test] Building Kasm Image...")
        result = self.run_command("docker build -t sanity-gravity:kasm -f sandbox/variants/kasm/Dockerfile sandbox")
        self.assertEqual(result.returncode, 0, f"Kasm build failed: {result.stderr}")

    def test_03_run_core_supervisord(self):
        print("\n[Test] Running Core Container...")
        # Run core container
        cmd = (
            "docker run -d --name sandbox-test-core "
            "-e HOST_UID=1001 "
            "-e HOST_GID=1001 "
            "-e HOST_USER=developer "
            "-e HOST_PASSWORD=antigravity "
            "sanity-gravity:core"
        )
        result = self.run_command(cmd)
        self.assertEqual(result.returncode, 0, "Failed to start core container")
        
        time.sleep(2) # Wait for startup

        # Check supervisord process
        check_cmd = "docker exec sandbox-test-core ps aux | grep supervisord"
        result = self.run_command(check_cmd)
        self.assertIn("/usr/bin/supervisord", result.stdout, "Supervisord not running in core")

    def test_04_run_kasm_and_check_port(self):
        print("\n[Test] Running Kasm Container...")
        # Run kasm container
        cmd = (
            "docker run -d --name sandbox-test-kasm "
            "-p 8445:8444 "
            "-e HOST_UID=1001 "
            "-e HOST_GID=1001 "
            "-e HOST_USER=developer "
            "-e HOST_PASSWORD=antigravity "
            "--shm-size=512m "
            "sanity-gravity:kasm"
        )
        result = self.run_command(cmd)
        self.assertEqual(result.returncode, 0, "Failed to start kasm container")

        print("Waiting for KasmVNC to start (10s)...")
        time.sleep(10)

        # Check if port is listening inside
        netstat = self.run_command("docker exec sandbox-test-kasm netstat -tulpn | grep 8444")
        self.assertIn("8444", netstat.stdout, "Port 8444 not listening inside container")

        # Check logs for success
        logs = self.run_command("docker logs sandbox-test-kasm")
        self.assertIn("success: kasmvnc entered RUNNING state", logs.stdout + logs.stderr, "KasmVNC did not enter RUNNING state")

    def test_05_check_user_mapping(self):
        print("\n[Test] Checking User Mapping...")
        # We passed UID 1001 in test_04
        result = self.run_command("docker exec sandbox-test-kasm id -u developer")
        self.assertEqual(result.stdout.strip(), "1001", "User UID not mapped correctly to 1001")
        
        result = self.run_command("docker exec sandbox-test-kasm id -g developer")
        self.assertEqual(result.stdout.strip(), "1001", "User GID not mapped correctly to 1001")

    def test_06_check_ssl_group(self):
        print("\n[Test] Checking SSL Group Membership...")
        result = self.run_command("docker exec sandbox-test-kasm groups developer")
        self.assertIn("ssl-cert", result.stdout, "User 'developer' not in 'ssl-cert' group")

    def test_07_check_http_response(self):
        print("\n[Test] Checking HTTP Connectivity...")
        # Curl the exposed port 8445 (mapped to 8444)
        # We use -k because of self-signed cert
        cmd = "curl -k -I https://localhost:8445"
        result = self.run_command(cmd)
        
        # KasmVNC might return 401 Unauthorized (Basic Auth) or 200 depending on path, 
        # but getting a response means it's working.
        # Based on previous curl output: HTTP/1.1 401 Unauthorized is expected for root without auth
        self.assertIn("HTTP/1.1", result.stdout, "No HTTP response received")
        # 401 is good, it means the server is there and protecting itself
        # 200 is also good if it serves the login page
        is_200_or_401 = "200 OK" in result.stdout or "401 Unauthorized" in result.stdout
        self.assertTrue(is_200_or_401, f"Unexpected HTTP status: {result.stdout}")

if __name__ == '__main__':
    unittest.main()
