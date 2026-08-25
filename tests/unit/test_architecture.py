"""Executable architecture: the import contracts in pyproject.toml.

Runs import-linter's CLI - the same entry point CI's lint job uses -
and fails with the linter's own report pasted into the assertion.

Deliberately no skip-if-not-installed: a missing lint-imports binary
must read as red, not as silently waived coverage. import-linter is
declared in both the lint and test extras precisely so every
environment that runs the unit suite can execute it (the packaging
contract test pins that).

The ignore_imports lists in [tool.importlinter] are frozen debt and may
only shrink. import-linter errors on unmatched ignores by default, so
retiring an edge without deleting its line is also red - the ratchet
enforces itself in both directions.
"""
import subprocess
import sys
from pathlib import Path

from tests.support import REPO_ROOT


def test_import_contracts_hold():
    # The script installed next to the running interpreter, never a
    # PATH lookup: a stray system-wide lint-imports must not be able to
    # answer for this environment.
    exe = Path(sys.executable).with_name("lint-imports")
    proc = subprocess.run(
        (str(exe),), cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, (
        "import-linter contracts violated (config: pyproject.toml "
        "[tool.importlinter]):\n" + proc.stdout + proc.stderr
    )
