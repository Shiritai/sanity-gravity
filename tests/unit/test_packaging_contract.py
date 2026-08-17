"""Packaging contract: dependencies have one source of truth.

Runtime deps live in [project.dependencies]; test-only deps live in the
"test" extra. CI must install through the package (-e ".[test]") so a
dependency added to pyproject.toml reaches CI without editing YAML.
"""
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_pyproject_declares_test_extra():
    data = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())
    extra = data["project"]["optional-dependencies"]["test"]
    assert {"pytest", "pytest-timeout", "requests", "urllib3"} <= set(extra)
    assert any(dep.startswith("hypothesis") for dep in extra)


def test_workflows_install_via_test_extra():
    """Any workflow step that installs packages must go through the
    test extra - a hand-copied dep list silently drifts from pyproject."""
    offenders = []
    for wf in sorted((_REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        for lineno, line in enumerate(wf.read_text().splitlines(), 1):
            if "pip install" not in line or "--upgrade pip" in line:
                continue
            if 'pip install -e ".[test]"' not in line:
                offenders.append(f"{wf.name}:{lineno}: {line.strip()}")
    assert not offenders, (
        "workflows must install deps via 'pip install -e \".[test]\"':\n"
        + "\n".join(offenders)
    )
