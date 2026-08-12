
import sys
import os
import unittest

from sanity_gravity.infra.proxy_manager import ProxyManager
from sanity_gravity.compose import generators as cli

class TestProxyStrict(unittest.TestCase):
    def setUp(self):
        # Determine config file path relative to CWD
        self.config_file = "config/docker-compose.git.yml"
        
        # Mock isatty to False
        if sys.stdin:
            sys.stdin.isatty = lambda: False
            
    def test_strict_policy(self):
        print(">>> Testing Strict Proxy Policy")
        
        pm = ProxyManager()
        
        # 1. Ensure Proxy is ENABLED
        print(" [1] Ensuring Proxy Enabled...")
        try:
            pm.setup()
        except Exception as e:
            self.fail(f"Setup failed: {e}")
            
        if not pm.is_enabled():
            self.fail("Proxy not enabled")
        else:
            socket_path = pm.get_socket_path()
            print(f"DEBUG: Proxy IS enabled. Socket: {socket_path} Exists: {os.path.exists(socket_path)}")
    
        # Run generate_git_compose (Proxy Enabled)
        print(" [2] Running generate_git_compose (Proxy Enabled)...")
        cli.generate_git_compose("testuser")
        
        # Check Result
        if not os.path.exists(self.config_file):
            self.fail("config file not generated")
        else:
            with open(self.config_file, "r") as f:
                content = f.read()
            if pm.get_socket_path() in content:
                print("PASS: Proxy socket found in config")
            else:
                 self.fail(f"Proxy socket NOT found in config. Content:\n{content}")
    
        # 2. Disable Proxy
        print(" [3] Disabling Proxy and Removing Socket...")
        pm.remove()
        if os.path.exists(pm.get_socket_path()):
            os.remove(pm.get_socket_path())
            
        # Run generate_git_compose (Proxy Missing)
        # Clear config file first
        if os.path.exists(self.config_file):
            os.remove(self.config_file)
            
        print(" [4] Running generate_git_compose (Proxy Missing)...")
        cli.generate_git_compose("testuser")
        
        if os.path.exists(self.config_file):
            with open(self.config_file, "r") as f:
                content = f.read()
                if "ssh-agent.sock" in content:
                     self.fail("SSH Agent socket found in Strict Mode! Should be skipped.")
                else:
                     print("PASS: Config generated without SSH Agent (Correctly Skipped)")
        else:
            print("PASS: No config generated (Correctly Skipped)")
    
        # Restore
        print(" [5] Restoring Proxy...")
        pm.setup()

if __name__ == "__main__":
    unittest.main()
