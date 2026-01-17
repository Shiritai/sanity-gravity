
import pytest
import subprocess
import socket
import time
import re
import os

def is_port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', int(port))) == 0

class TestCLIPorts:
    @pytest.fixture
    def cli(self):
        def _run(args):
            # Assume running from project root
            cmd = f"./sanity-cli {args}"
            return subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return _run

    def test_explicit_port_assignment(self, cli):
        """Test that explicit port assignment (-p) is respected even with custom names."""
        name = "test-explicit-port"
        port = "2299"
        
        # Ensure clean state
        cli(f"down -n {name}")
        
        try:
            res = cli(f"up -v core -p {port} -n {name} --skip-check")
            assert res.returncode == 0
            
            # Check output for assigned port
            match = re.search(r"ssh -p (\d+)", res.stdout)
            assert match, "Could not find SSH port in output"
            assigned_port = match.group(1)
            assert assigned_port == port, f"Expected port {port}, got {assigned_port}"
            
            # Verify port is actually open
            # Note: It might take a split second for docker proxy to bind
            time.sleep(1)
            assert is_port_open(port), f"Port {port} should be open"
            
        finally:
            # Cleanup
            cli(f"down -n {name}")
            
    def test_port_release_after_down(self, cli):
        """Test that ports are correctly released after down command."""
        name = "test-port-release"
        
        # Ensure clean state
        cli(f"down -n {name}")
        
        assigned_ports = []
        try:
            # Start with auto-assign (kasm has multiple ports)
            res = cli(f"up -v kasm -n {name} --skip-check")
            assert res.returncode == 0
            
            # Extract ports
            # Kasm output: URL: https://localhost:32805, SSH: ssh -p 32804
            matches_ssh = re.findall(r"ssh -p (\d+)", res.stdout)
            matches_kasm = re.findall(r"localhost:(\d+)", res.stdout)
            
            assigned_ports = [int(p) for p in matches_ssh + matches_kasm]
            # Remove duplicates if any
            assigned_ports = list(set(assigned_ports))
            
            assert len(assigned_ports) > 0, "No ports assigned?"
            print(f"Assigned ports: {assigned_ports}")
            
            # Verify they are open
            time.sleep(1)
            for p in assigned_ports:
                assert is_port_open(p), f"Port {p} should be open"
                
        finally:
            # Down
            cli(f"down -n {name}")
            
        # Verify they are closed
        time.sleep(3) # Give docker a moment to clean up proxies
        for p in assigned_ports:
            assert not is_port_open(p), f"Port {p} should be closed after down"
