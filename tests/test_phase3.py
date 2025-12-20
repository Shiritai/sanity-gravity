import unittest
import subprocess
import time
import os

class TestSandboxPhase3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print("\n[Setup] Cleaning up old containers...")
        subprocess.run("./sanity-cli stop", shell=True, stderr=subprocess.DEVNULL)
        subprocess.run("docker rm -f sanity-gravity-kasm-1 sandbox-debug sandbox-kasm sandbox-vnc", shell=True, stderr=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):
        print("\n[Teardown] Cleaning up containers...")
        subprocess.run("./sanity-cli stop", shell=True, stderr=subprocess.DEVNULL)

    def run_command(self, cmd):
        return subprocess.run(cmd, shell=True, capture_output=True, text=True)

    def test_01_cli_help(self):
        print("\n[Test] Checking CLI Help...")
        result = self.run_command("./sanity-cli --help")
        self.assertEqual(result.returncode, 0, "CLI help failed")
        self.assertIn("Antigravity Sandbox CLI", result.stdout, "CLI help text mismatch")

    def test_02_cli_list(self):
        print("\n[Test] Checking CLI List...")
        result = self.run_command("./sanity-cli list")
        self.assertEqual(result.returncode, 0, "CLI list failed")
        self.assertIn("kasm", result.stdout, "Variant 'kasm' not found in list")

    def test_03_cli_build_core(self):
        print("\n[Test] CLI Build Core...")
        result = self.run_command("./sanity-cli build core")
        self.assertEqual(result.returncode, 0, f"CLI build core failed: {result.stderr}")

    def test_04_cli_run_kasm(self):
        print("\n[Test] CLI Run Kasm...")
        # Note: The CLI uses docker compose, so the container name will likely be project_service_index
        # We assume the directory name 'sanity-gravity' -> 'sanity-gravity-kasm-1' or similar.
        # But we can check via docker ps filtering by image.
        
        result = self.run_command("./sanity-cli run --variant kasm")
        self.assertEqual(result.returncode, 0, f"CLI run kasm failed: {result.stderr}")

        print("Waiting for Kasm to start (5s)...")
        time.sleep(5)

        # Check if container is running
        ps = self.run_command("docker ps --filter ancestor=sanity-gravity:kasm --format '{{.Names}}'")
        self.assertTrue(len(ps.stdout.strip()) > 0, "Kasm container not found running")

    def test_05_cli_stop(self):
        print("\n[Test] CLI Stop...")
        result = self.run_command("./sanity-cli stop")
        self.assertEqual(result.returncode, 0, "CLI stop failed")
        
        time.sleep(2)
        
        # Check if container is gone
        ps = self.run_command("docker ps --filter ancestor=sanity-gravity:kasm --format '{{.Names}}'")
        self.assertEqual(len(ps.stdout.strip()), 0, "Kasm container still running after stop")

if __name__ == '__main__':
    unittest.main()
