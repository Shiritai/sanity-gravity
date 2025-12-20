import unittest
import subprocess
import time
import os

class TestSandboxPhase4(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print("\n[Setup] Cleaning up old containers...")
        subprocess.run("./sanity-cli stop", shell=True, stderr=subprocess.DEVNULL)
        subprocess.run("docker rm -f sanity-gravity-core-1", shell=True, stderr=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):
        print("\n[Teardown] Cleaning up containers...")
        subprocess.run("./sanity-cli stop", shell=True, stderr=subprocess.DEVNULL)

    def run_command(self, cmd):
        return subprocess.run(cmd, shell=True, capture_output=True, text=True)

    def test_01_build_core(self):
        print("\n[Test] Building Core Image (with SSH & Chrome)...")
        result = self.run_command("./sanity-cli build core")
        self.assertEqual(result.returncode, 0, f"Core build failed: {result.stderr}")

    def test_02_run_core(self):
        print("\n[Test] Running Core Container...")
        # Create a dummy workspace to test permissions
        os.makedirs("workspace", exist_ok=True)
        # Create a file owned by root (simulated by just creating it, docker mount might change it)
        # Actually, we rely on entrypoint to chown it to HOST_UID
        
        result = self.run_command("./sanity-cli run --variant core")
        self.assertEqual(result.returncode, 0, f"Core run failed: {result.stderr}")
        
        print("Waiting for Core to start (5s)...")
        time.sleep(5)

    def get_container_name(self, image_name):
        cmd = f"docker ps --filter ancestor={image_name} --format '{{{{.Names}}}}'"
        result = self.run_command(cmd)
        return result.stdout.strip()

    def test_03_check_ssh_service(self):
        print("\n[Test] Checking SSH Service...")
        container_name = self.get_container_name("sanity-gravity:core")
        self.assertTrue(container_name, "Core container not found")
        
        # Check if sshd is running
        ps = self.run_command(f"docker exec {container_name} ps aux | grep sshd")
        self.assertIn("/usr/sbin/sshd", ps.stdout, "SSHD process not running")
        
        # Check if port 22 is listening
        netstat = self.run_command(f"docker exec {container_name} netstat -tulpn | grep :22")
        self.assertIn("LISTEN", netstat.stdout, "Port 22 not listening")

    def test_04_check_chrome_install(self):
        print("\n[Test] Checking Google Chrome Installation...")
        container_name = self.get_container_name("sanity-gravity:core")
        
        # Get host user
        import pwd
        host_user = pwd.getpwuid(os.getuid()).pw_name

        result = self.run_command(f"docker exec -u {host_user} {container_name} google-chrome --version")
        self.assertEqual(result.returncode, 0, f"Google Chrome check failed: {result.stderr}")
        self.assertIn("Google Chrome", result.stdout, "Google Chrome version string mismatch")

    def test_05_check_volume_permissions(self):
        print("\n[Test] Checking Workspace Permissions and User Sync...")
        container_name = self.get_container_name("sanity-gravity:core")
        
        # Get host user details
        import pwd
        host_uid = str(os.getuid())
        host_user = pwd.getpwuid(os.getuid()).pw_name
        
        print(f"Expectation: Container should have user '{host_user}' with UID {host_uid}")

        # Check if user exists in container
        user_check = self.run_command(f"docker exec {container_name} id -u {host_user}")
        self.assertEqual(user_check.returncode, 0, f"User '{host_user}' not found in container")
        self.assertEqual(user_check.stdout.strip(), host_uid, f"Container user '{host_user}' has wrong UID")
        
        # Check owner of workspace
        stat_res = self.run_command(f"docker exec {container_name} stat -c '%u' /home/{host_user}/workspace")
        owner = stat_res.stdout.strip()
        
        self.assertEqual(host_uid, owner, f"Workspace owner ({owner}) does not match host UID ({host_uid})")

if __name__ == '__main__':
    unittest.main()
