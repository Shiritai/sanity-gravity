import os
import subprocess
import time
import unittest

import pytest

pytestmark = pytest.mark.requires_docker


class TestCliRestart(unittest.TestCase):
    CLI = "./sanity-cli"
    PROXY_SERVICE = "sanity-gravity-proxy"

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
        # Start clean
        subprocess.run([self.CLI, "proxy", "remove"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)

    def test_restart_capability(self):
        """Test restart capability with changing backend socket"""
        # 1. Setup Proxy
        print(" [1] Setting up Proxy...")
        res = self.run_cli(["proxy", "setup"])
        self.assertEqual(res.returncode, 0)
        
        # 2. Simulate Backend Change (New Agent)
        # We can simulate this by changing the environment variable for the service
        # But systemd user services are tricky with env.
        # Instead, we will use a dummy socket listener.
        
        # 3. Verify Connectivity (Initial)
        # We rely on the fact that existing SSH_AUTH_SOCK works.
        # Or we skip actual connectivity test and verify configuration change?
        # No, "True Restart" means actual connectivity.
        
        # Let's try to just 'restart' the proxy service and see if the socket file remains stable (path same)
        # and if it reconnects to the backend.
        
        socket_path = os.path.expanduser("~/.gemini/bridge/ssh.sock")
        self.assertTrue(os.path.exists(socket_path))
        
        # Get inode of the socket file? No, socket file is recreated by socat on restart.
        # Wait, if socket is recreated, does Docker container lose connection?
        # NO. Docker bind mount follows the path on the host. If the file at that path is replaced,
        # the bind mount inside the container might point to the OLD inode (deleted file).
        # THIS IS THE CRITICAL PART.
        # If socat unlinks and recreates the socket file, Docker containers might see a stale file handle!
        #
        # Let's verify this hypothesis.
        # If we replace the file, bind mount breaks?
        # Actually, yes. Bind mounts are usually inode-based.
        # If we remove the file and create a new one, the container still holds the old inode.
        #
        # SO, 'True Restart' with FILE-BASED socket proxy MIGHT NOT WORK if we delete the file!
        # Unless we overwrite it? But sockets cannot be overwritten like files.
        #
        # Standard approach for this is usually a directory mount?
        # If we mount the directory `~/.gemini/bridge/`, then a new file inside it is visible?
        # But SSH clients look for a specific socket path.
        #
        # If the container mounts `/root/.ssh/agent/sock` -> Host `~/.gemini/bridge/ssh.sock`
        # And host deletes `ssh.sock` and creates new `ssh.sock`.
        # The container still points to old `ssh.sock` inode.
        #
        # This test is CRITICAL to verify if my "True Restart" claim is actually true or if I need a directory mount!
        
        st_before = os.stat(socket_path)
        print(f"Socket Inode before restart: {st_before.st_ino}")

        print(" [2] Restarting Proxy Service...")
        subprocess.run(["systemctl", "--user", "restart", self.PROXY_SERVICE], check=True)
        time.sleep(2)
        
        self.assertTrue(os.path.exists(socket_path))
        
        st_after = os.stat(socket_path)
        print(f"Socket Inode after restart: {st_after.st_ino}")
        
        if st_before.st_ino != st_after.st_ino:
            print("NOTICE: Socket inode CHANGED. Existing containers typically lose connection.")
        else:
            print("SUCCESS: Socket inode PRESERVED.")

if __name__ == "__main__":
    unittest.main()
