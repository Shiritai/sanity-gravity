import os
import subprocess
import unittest

import pytest

pytestmark = pytest.mark.requires_docker


class TestCliProxy(unittest.TestCase):
    CLI = "./sanity-cli"

    def run_cli(self, args):
        """Helper to run CLI command"""
        cmd = [self.CLI] + args
        result = subprocess.run(
            cmd, 
            capture_output=True,
            text=True
        )
        return result

    def setUp(self):
        # Ensure clean state
        subprocess.run([self.CLI, "proxy", "remove"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def test_status_not_setup(self):
        """Test 'status' when not set up"""
        res = self.run_cli(["proxy", "status"])
        self.assertEqual(res.returncode, 0)
        self.assertIn("Not Setup", res.stdout)

    def test_setup_and_status(self):
        """Test 'setup' and then 'status'"""
        # Setup
        res = self.run_cli(["proxy", "setup"])
        self.assertEqual(res.returncode, 0)
        self.assertIn("SSH Proxy enabled", res.stdout)
        
        # Status
        res = self.run_cli(["proxy", "status"])
        self.assertEqual(res.returncode, 0)
        self.assertIn("Enabled", res.stdout)
        self.assertIn("Active:     \x1b[92mRunning\x1b[0m", res.stdout.replace(os.linesep, "\n"))
        self.assertIn("Socket:     \x1b[92mPresent\x1b[0m", res.stdout.replace(os.linesep, "\n"))

    def test_remove(self):
        """Test 'remove'"""
        # Setup first
        self.run_cli(["proxy", "setup"])
        
        # Remove
        res = self.run_cli(["proxy", "remove"])
        self.assertEqual(res.returncode, 0)
        self.assertIn("removed", res.stdout)
        
        # Check status
        res = self.run_cli(["proxy", "status"])
        self.assertIn("Not Setup", res.stdout)

if __name__ == "__main__":
    unittest.main()
