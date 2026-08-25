import os
import stat
import subprocess
import tempfile
import textwrap

import pytest

pytestmark = pytest.mark.no_image

GRAVITY_CLI_PATH = os.path.abspath("plugins/agents/ag/rootfs/usr/local/bin/gravity-cli")

def create_mock_command(dir_path, name, script_content):
    path = os.path.join(dir_path, name)
    with open(path, "w") as f:
        f.write(script_content)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)

def get_bypassed_script(tmpdir):
    with open(GRAVITY_CLI_PATH) as f:
        content = f.read()
    
    # Bypass EUID check
    content = content.replace('[ "$EUID" -ne 0 ]', 'false')
    
    # Divert persistent paths to tmpdir so we can test safely without root
    sandbox_dir = os.path.join(tmpdir, "antigravity")
    os.makedirs(sandbox_dir, exist_ok=True)
    content = content.replace('/usr/share/antigravity', sandbox_dir)
    
    home_dir = os.path.join(tmpdir, "home")
    os.makedirs(home_dir, exist_ok=True)
    content = content.replace('/home', home_dir)

    opt_chrome_dir = os.path.join(tmpdir, "opt", "google", "chrome")
    os.makedirs(opt_chrome_dir, exist_ok=True)
    content = content.replace('/opt/google/chrome', opt_chrome_dir)

    out_path = os.path.join(tmpdir, "gravity-cli-bypassed")
    with open(out_path, "w") as f:
        f.write(content)
    os.chmod(out_path, os.stat(out_path).st_mode | stat.S_IEXEC)
    return out_path

def test_gravity_cli_update_ide_success():
    with tempfile.TemporaryDirectory() as tmpdir:
        bypassed_cli = get_bypassed_script(tmpdir)
        create_mock_command(tmpdir, "apt-get", "#!/bin/bash\necho \"Mock apt-get $@\"\nexit 0")
        create_mock_command(tmpdir, "dpkg-divert", "#!/bin/bash\necho \"Mock dpkg-divert $@\"\nexit 0")
        create_mock_command(tmpdir, "find", "#!/bin/bash\necho \"Mock find $@\"\nexit 0")
        create_mock_command(tmpdir, "rm", "#!/bin/bash\necho \"Mock rm $@\"\nexit 0")
        
        env = os.environ.copy()
        env["PATH"] = f"{tmpdir}:{env.get('PATH', '')}"
        
        result = subprocess.run(
            ["bash", bypassed_cli, "ide", "update"],
            env=env,
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0
        assert "Updating package lists" in result.stdout
        assert "Mock apt-get update -y" in result.stdout
        assert "Mock apt-get install --only-upgrade -y antigravity" in result.stdout
        assert "IDE update completed successfully" in result.stdout
        
        # Verify Antigravity robust wrapper creation
        ag_wrapper_path = os.path.join(tmpdir, "antigravity", "antigravity")
        assert os.path.exists(ag_wrapper_path)
        with open(ag_wrapper_path) as f:
            ag_wrapper_content = f.read()
            
        expected_wrapper = textwrap.dedent(f"""\
            #!/bin/bash
            # Master Wrapper for Antigravity in Kasm Sandbox
            
            # 1. Environment Fix for Electron Children
            export ELECTRON_DISABLE_SANDBOX=1
            
            # 2. Process Type Detection
            IS_GUI_CHILD=0
            for arg in "$@"; do
                if [[ "$arg" == --type=* ]]; then
                    IS_GUI_CHILD=1
                    break
                fi
            done
            
            # 3. Execution Logic
            if [ "$ELECTRON_RUN_AS_NODE" = "1" ] && [ "$IS_GUI_CHILD" = "0" ]; then
                # Pure CLI Node mode - NO sandbox flags allowed here
                exec {tmpdir}/antigravity/antigravity-bin "$@"
            fi
            
            # Everything else is a GUI process or a child process requiring Chromium flags
            unset ELECTRON_RUN_AS_NODE
            exec {tmpdir}/antigravity/antigravity-bin \\
                --no-sandbox \\
                --disable-dev-shm-usage \\
                --disable-zygote \\
                --disable-namespace-sandbox \\
                "$@"
            """)
        assert ag_wrapper_content == expected_wrapper

        # Verify Google Chrome robust wrapper creation
        chrome_wrapper_path = os.path.join(tmpdir, "opt", "google", "chrome", "google-chrome")
        assert os.path.exists(chrome_wrapper_path)
        with open(chrome_wrapper_path) as f:
            chrome_wrapper_content = f.read()
        assert chrome_wrapper_content == f'#!/bin/bash\nexec {tmpdir}/opt/google/chrome/google-chrome-original --no-sandbox --disable-dev-shm-usage "$@"\n'

def test_gravity_cli_update_ide_failure():
    with tempfile.TemporaryDirectory() as tmpdir:
        bypassed_cli = get_bypassed_script(tmpdir)
        create_mock_command(tmpdir, "apt-get", "#!/bin/bash\nif [[ \"$*\" == *\"install\"* ]]; then exit 1; fi\nexit 0\n")
        create_mock_command(tmpdir, "dpkg-divert", "#!/bin/bash\nexit 0")
        
        env = os.environ.copy()
        env["PATH"] = f"{tmpdir}:{env.get('PATH', '')}"
        
        result = subprocess.run(
            ["bash", bypassed_cli, "ide", "update"],
            env=env,
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 1
        assert "Failed to update package." in result.stdout

def test_gravity_cli_reinstall_ide_success():
    with tempfile.TemporaryDirectory() as tmpdir:
        bypassed_cli = get_bypassed_script(tmpdir)
        create_mock_command(tmpdir, "apt-get", "#!/bin/bash\necho \"Mock apt-get $@\"\nexit 0")
        create_mock_command(tmpdir, "dpkg-divert", "#!/bin/bash\necho \"Mock dpkg-divert $@\"\nexit 0")
        create_mock_command(tmpdir, "find", "#!/bin/bash\necho \"Mock find $@\"\nexit 0")
        create_mock_command(tmpdir, "rm", "#!/bin/bash\necho \"Mock rm $@\"\nexit 0")
        
        env = os.environ.copy()
        env["PATH"] = f"{tmpdir}:{env.get('PATH', '')}"
        
        result = subprocess.run(
            ["bash", bypassed_cli, "ide", "reinstall"],
            env=env,
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0
        assert "Removing existing Antigravity IDE" in result.stdout
        assert "Mock apt-get remove --purge -y antigravity" in result.stdout
        assert "Mock apt-get install -y antigravity" in result.stdout
        assert "IDE Reinstallation completed successfully." in result.stdout
        
        # Verify Antigravity robust wrapper creation
        ag_wrapper_path = os.path.join(tmpdir, "antigravity", "antigravity")
        assert os.path.exists(ag_wrapper_path)
        with open(ag_wrapper_path) as f:
            ag_wrapper_content = f.read()
        
        expected_wrapper = textwrap.dedent(f"""\
            #!/bin/bash
            # Master Wrapper for Antigravity in Kasm Sandbox
            
            # 1. Environment Fix for Electron Children
            export ELECTRON_DISABLE_SANDBOX=1
            
            # 2. Process Type Detection
            IS_GUI_CHILD=0
            for arg in "$@"; do
                if [[ "$arg" == --type=* ]]; then
                    IS_GUI_CHILD=1
                    break
                fi
            done
            
            # 3. Execution Logic
            if [ "$ELECTRON_RUN_AS_NODE" = "1" ] && [ "$IS_GUI_CHILD" = "0" ]; then
                # Pure CLI Node mode - NO sandbox flags allowed here
                exec {tmpdir}/antigravity/antigravity-bin "$@"
            fi
            
            # Everything else is a GUI process or a child process requiring Chromium flags
            unset ELECTRON_RUN_AS_NODE
            exec {tmpdir}/antigravity/antigravity-bin \\
                --no-sandbox \\
                --disable-dev-shm-usage \\
                --disable-zygote \\
                --disable-namespace-sandbox \\
                "$@"
            """)
        assert ag_wrapper_content == expected_wrapper

        # Verify Google Chrome robust wrapper creation
        chrome_wrapper_path = os.path.join(tmpdir, "opt", "google", "chrome", "google-chrome")
        assert os.path.exists(chrome_wrapper_path)
        with open(chrome_wrapper_path) as f:
            chrome_wrapper_content = f.read()
        assert chrome_wrapper_content == f'#!/bin/bash\nexec {tmpdir}/opt/google/chrome/google-chrome-original --no-sandbox --disable-dev-shm-usage "$@"\n'

def test_gravity_cli_invalid_command():
    with tempfile.TemporaryDirectory() as tmpdir:
        bypassed_cli = get_bypassed_script(tmpdir)
        result = subprocess.run(
            ["bash", bypassed_cli, "unknown-cmd"],
            capture_output=True,
            text=True
        )
        assert result.returncode == 1
        assert "Usage: gravity-cli <command> [options]" in result.stdout
