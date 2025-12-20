import unittest
import subprocess
import time
import requests

class TestSandboxPhase2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print("\n[Setup] Cleaning up old containers...")
        subprocess.run("docker rm -f sandbox-test-vnc", shell=True, stderr=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):
        print("\n[Teardown] Cleaning up containers...")
        subprocess.run("docker rm -f sandbox-test-vnc", shell=True, stderr=subprocess.DEVNULL)

    def run_command(self, cmd):
        return subprocess.run(cmd, shell=True, capture_output=True, text=True)

    def test_01_build_vnc(self):
        print("\n[Test] Building VNC Image...")
        result = self.run_command("docker build -t sanity-gravity:vnc -f sandbox/variants/vnc/Dockerfile sandbox")
        self.assertEqual(result.returncode, 0, f"VNC build failed: {result.stderr}")

    def test_02_run_vnc_and_check_ports(self):
        print("\n[Test] Running VNC Container...")
        cmd = (
            "docker run -d --name sandbox-test-vnc "
            "-p 5902:5901 -p 6902:6901 "
            "-e HOST_UID=1001 "
            "-e HOST_GID=1001 "
            "-e HOST_USER=developer "
            "-e HOST_PASSWORD=antigravity "
            "-e VNC_PW=antigravity "
            "-e VNC_RESOLUTION=1280x720 "
            "-e VNC_DEPTH=24 "
            "--shm-size=512m "
            "sanity-gravity:vnc"
        )
        result = self.run_command(cmd)
        self.assertEqual(result.returncode, 0, "Failed to start VNC container")

        print("Waiting for VNC to start (5s)...")
        time.sleep(5)

        # Check ports inside
        netstat = self.run_command("docker exec sandbox-test-vnc netstat -tulpn")
        self.assertIn("5901", netstat.stdout, "Port 5901 (VNC) not listening")
        self.assertIn("6901", netstat.stdout, "Port 6901 (noVNC) not listening")

    def test_03_check_novnc_http(self):
        print("\n[Test] Checking noVNC HTTP Connectivity...")
        try:
            response = requests.get("http://localhost:6902/vnc.html", timeout=5)
            self.assertEqual(response.status_code, 200, "noVNC index page did not return 200")
            self.assertIn("noVNC", response.text, "noVNC page content mismatch")
        except requests.exceptions.RequestException as e:
            self.fail(f"HTTP request failed: {e}")

if __name__ == '__main__':
    unittest.main()
