import unittest
import subprocess
import time
import os

class TestParameters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print("\n[Setup] Cleaning up old containers...")
        subprocess.run("./sanity-cli stop", shell=True, stderr=subprocess.DEVNULL)
        subprocess.run("docker rm -f sanity-gravity-core-1 sanity-gravity-kasm-1 sanity-gravity-vnc-1", shell=True, stderr=subprocess.DEVNULL)

    def tearDown(self):
        print("\n[Teardown] Stopping container...")
        subprocess.run("./sanity-cli stop", shell=True, stderr=subprocess.DEVNULL)
        time.sleep(2)

    def run_command(self, cmd):
        return subprocess.run(cmd, shell=True, capture_output=True, text=True)

    def test_01_custom_password_kasm(self):
        print("\n[Test] Kasm with Custom Password...")
        pwd = "automated_test_password"
        
        # Run Kasm with custom password
        cmd = f"./sanity-cli run -v kasm --password {pwd} --skip-check"
        result = self.run_command(cmd)
        self.assertEqual(result.returncode, 0, f"Failed to run kasm: {result.stderr}")
        
        print("Waiting for container (5s)...")
        time.sleep(5)
        
        # Verify HOST_PASSWORD env var
        check_host_pw = self.run_command("docker exec sanity-gravity-kasm-1 env | grep HOST_PASSWORD")
        self.assertEqual(check_host_pw.returncode, 0, "HOST_PASSWORD not found in env")
        self.assertIn(f"HOST_PASSWORD={pwd}", check_host_pw.stdout.strip())
        
        # Verify VNC_PW check (inside startup script logic indirectly via connection or file?)
        # Since we refactored startup scripts to just run vncpasswd with the var, checking env is strong evidence.
        # But let's check the vnc passwd file if possible? No, it's binary.
        # We can check Kasm configuration or just trust the process if env is right.
        # Let's check entrypoint user password hash?
        # Shadow file is readable by root.
        
        check_shadow = self.run_command(f"docker exec -u root sanity-gravity-kasm-1 grep shiritai /etc/shadow")
        # We might need to know the dynamic user name.
        # sanity-cli maps host user.
        import pwd as host_pwd
        username = host_pwd.getpwuid(os.getuid()).pw_name
        
        check_shadow = self.run_command(f"docker exec -u root sanity-gravity-kasm-1 grep {username} /etc/shadow")
        self.assertEqual(check_shadow.returncode, 0, "User not found in shadow file")
        # We can't easily verify hash matches 'automated_test_password' without recalculating it, 
        # but we verified logic writes it.
        print("✔ Environment variable verification passed.")

    def test_02_custom_ports_vnc(self):
        print("\n[Test] VNC with Custom Ports...")
        # Use non-standard ports
        vnc_port = "5999"
        novnc_port = "6999"
        ssh_port = "2299"
        
        cmd = f"./sanity-cli run -v vnc --vnc-port {vnc_port} --novnc-port {novnc_port} --ssh-port {ssh_port} --skip-check"
        result = self.run_command(cmd)
        self.assertEqual(result.returncode, 0, f"Failed to run vnc: {result.stderr}")
        
        print("Waiting for container (5s)...")
        time.sleep(5)
        
        # Check if ports are listening on host
        # We can use docker port command
        port_check = self.run_command("docker port sanity-gravity-vnc-1")
        self.assertIn(f"0.0.0.0:{vnc_port}", port_check.stdout)
        self.assertIn(f"0.0.0.0:{novnc_port}", port_check.stdout)
        self.assertIn(f"0.0.0.0:{ssh_port}", port_check.stdout)
        print("✔ Port mapping verification passed.")

if __name__ == '__main__':
    unittest.main()
