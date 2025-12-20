import unittest
import subprocess
import time
import os

class TestEnhancedCLI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print("\n[Setup] Cleaning up...")
        subprocess.run("./sanity-cli stop", shell=True, stderr=subprocess.DEVNULL)

    def run_command(self, cmd):
        return subprocess.run(cmd, shell=True, capture_output=True, text=True)

    def test_01_cli_check(self):
        print("\n[Test] CLI Check...")
        result = self.run_command("./sanity-cli check")
        self.assertEqual(result.returncode, 0, "CLI check failed")
        self.assertIn("Docker is installed", result.stdout)
        self.assertIn("Docker Compose is installed", result.stdout)

    def test_02_cli_list(self):
        print("\n[Test] CLI List...")
        result = self.run_command("./sanity-cli list")
        self.assertEqual(result.returncode, 0, "CLI list failed")
        self.assertIn("kasm", result.stdout)

    def test_03_cli_status_empty(self):
        print("\n[Test] CLI Status (Empty)...")
        result = self.run_command("./sanity-cli status")
        self.assertEqual(result.returncode, 0, "CLI status failed")
        # Should be empty or header only

    def test_04_cli_install_build(self):
        print("\n[Test] CLI Install (Build)...")
        # We'll just build 'core' to save time
        result = self.run_command("./sanity-cli build core")
        self.assertEqual(result.returncode, 0, "CLI build core failed")

    def test_05_cli_run_status_stop(self):
        print("\n[Test] CLI Run -> Status -> Stop...")
        
        # Run
        run_res = self.run_command("./sanity-cli run --variant core --skip-check")
        self.assertEqual(run_res.returncode, 0, "CLI run failed")
        
        time.sleep(2)
        
        # Status
        status_res = self.run_command("./sanity-cli status")
        self.assertEqual(status_res.returncode, 0, "CLI status failed")
        self.assertIn("sanity-gravity-core-1", status_res.stdout)
        
        # Stop
        stop_res = self.run_command("./sanity-cli stop")
        self.assertEqual(stop_res.returncode, 0, "CLI stop failed")

if __name__ == '__main__':
    unittest.main()
