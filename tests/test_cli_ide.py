import pytest
import sys
import os
import subprocess
import argparse
from unittest.mock import patch, MagicMock

import importlib.util
from importlib.machinery import SourceFileLoader

def load_sanity_cli():
    if "sanity_cli" in sys.modules:
        return sys.modules["sanity_cli"]
        
    file_path = os.path.abspath("sanity-cli")
    loader = SourceFileLoader("sanity_cli", file_path)
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("sanity_cli", loader))
    sys.modules["sanity_cli"] = module
    loader.exec_module(module)
    return module

sanity_cli = load_sanity_cli()

class TestIdeCommand:
    @patch("sanity_cli.run_command")
    @patch("subprocess.check_call")
    @patch("sanity_cli.get_active_projects")
    def test_ide_update_success(self, mock_get_active, mock_check_call, mock_run):
        mock_get_active.return_value = ["sanity-gravity"]
        mock_run.return_value = "true"  # container running
        
        args = argparse.Namespace(name="sanity-gravity", ide_command="update-ide")
        
        sanity_cli.ide_cmd(args)
        
        cname = "sanity-gravity-ag-xfce-ssh-1"
        base_dir = os.path.dirname(os.path.abspath(sanity_cli.__file__))
        cli_src = os.path.join(base_dir, "sandbox", "rootfs", "usr", "local", "bin", "gravity-cli")
        cleanup_src = os.path.join(base_dir, "sandbox", "rootfs", "usr", "local", "bin", "chrome-cleanup.sh")
        
        expected_calls = [
            ((f"docker cp {cli_src} {cname}:/usr/local/bin/gravity-cli",), {"shell": True, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}),
            ((f"docker cp {cleanup_src} {cname}:/usr/local/bin/chrome-cleanup.sh",), {"shell": True, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}),
            ((f"docker exec -u root {cname} chmod +x /usr/local/bin/gravity-cli /usr/local/bin/chrome-cleanup.sh",), {"shell": True, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}),
            ((f"docker exec -it -u root {cname} /usr/local/bin/gravity-cli update-ide",), {"shell": True})
        ]
        assert mock_check_call.call_args_list == expected_calls
        
    @patch("sanity_cli.run_command")
    @patch("subprocess.check_call")
    @patch("sanity_cli.get_active_projects")
    def test_ide_reinstall_success(self, mock_get_active, mock_check_call, mock_run):
        mock_get_active.return_value = ["my-project"]
        mock_run.return_value = "true"  # container running
        
        args = argparse.Namespace(name="my-project", ide_command="reinstall-ide")
        
        sanity_cli.ide_cmd(args)
        
        cname = "my-project-ag-xfce-ssh-1"
        base_dir = os.path.dirname(os.path.abspath(sanity_cli.__file__))
        cli_src = os.path.join(base_dir, "sandbox", "rootfs", "usr", "local", "bin", "gravity-cli")
        cleanup_src = os.path.join(base_dir, "sandbox", "rootfs", "usr", "local", "bin", "chrome-cleanup.sh")

        expected_calls = [
            ((f"docker cp {cli_src} {cname}:/usr/local/bin/gravity-cli",), {"shell": True, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}),
            ((f"docker cp {cleanup_src} {cname}:/usr/local/bin/chrome-cleanup.sh",), {"shell": True, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}),
            ((f"docker exec -u root {cname} chmod +x /usr/local/bin/gravity-cli /usr/local/bin/chrome-cleanup.sh",), {"shell": True, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}),
            ((f"docker exec -it -u root {cname} /usr/local/bin/gravity-cli reinstall-ide",), {"shell": True})
        ]
        assert mock_check_call.call_args_list == expected_calls

    @patch("sanity_cli.get_active_projects")
    @patch("builtins.print")
    def test_ide_container_not_found(self, mock_print, mock_get_active):
        mock_get_active.return_value = ["other-project"]
        
        args = argparse.Namespace(name="non-existent-project", ide_command="update-ide")
        
        sanity_cli.ide_cmd(args)
        
        printed = [call_args[0][0] for call_args in mock_print.call_args_list]
        assert any("is not active or managed" in text for text in printed)
