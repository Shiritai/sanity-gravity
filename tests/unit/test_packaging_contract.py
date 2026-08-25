"""Packaging contract: dependencies have one source of truth.

Runtime deps live in [project.dependencies]; tool deps live in extras
("test" for the suite, "lint" for ruff). CI must install through the
package (-e ".[<extra>]") so a dependency added to pyproject.toml
reaches CI without editing YAML.
"""
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _extras() -> dict[str, list[str]]:
    data = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())
    return data["project"]["optional-dependencies"]


def test_pyproject_declares_test_extra():
    extra = _extras()["test"]
    assert {"pytest", "requests", "urllib3"} <= set(extra)
    assert any(dep.startswith("hypothesis") for dep in extra)
    # pytest-timeout left when its explicit -p reload did: the suite has
    # no timeout markers and pytest.ini configures none, so the extra
    # must not pin a plugin nothing loads. It re-enters (dep + -p)
    # together with the first real timeout marker.
    assert not any(dep.startswith("pytest-timeout") for dep in extra)
    # test_architecture.py shells out to lint-imports with no
    # skip-if-not-installed; dropping the dep here would turn that
    # guard red everywhere the unit suite runs.
    assert any(dep.startswith("import-linter") for dep in extra)


def test_pyproject_declares_lint_extra():
    """The lint job installs through this extra; a tool leaving it
    would turn its CI lint step into a no-op crash, not a soft skip."""
    extra = _extras()["lint"]
    assert any(dep.startswith("ruff") for dep in extra)
    assert any(dep.startswith("import-linter") for dep in extra)


def test_workflows_install_via_declared_extras():
    """Any workflow step that installs packages must go through a
    declared extra - a hand-copied dep list silently drifts from
    pyproject. The allowlist is derived from pyproject itself so a new
    extra needs no edit here, while a raw `pip install ruff` stays red."""
    allowed = {f'pip install -e ".[{name}]"' for name in _extras()}
    offenders = []
    for wf in sorted((_REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        for lineno, line in enumerate(wf.read_text().splitlines(), 1):
            if "pip install" not in line or "--upgrade pip" in line:
                continue
            if not any(form in line for form in allowed):
                offenders.append(f"{wf.name}:{lineno}: {line.strip()}")
    assert not offenders, (
        "workflows must install deps via 'pip install -e \".[<extra>]\"' "
        f"for a declared extra {sorted(_extras())}:\n" + "\n".join(offenders)
    )


def test_workflows_running_the_suite_require_images():
    """Any workflow step that runs ./sanity-cli test must set
    SANITY_REQUIRE_IMAGES: a suite that may skip is a suite that may lie
    (a mistyped build/pull loop would otherwise read as all-green)."""
    offenders = []
    for wf in sorted((_REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        text = wf.read_text()
        if "sanity-cli test" in text and "SANITY_REQUIRE_IMAGES" not in text:
            offenders.append(wf.name)
    assert not offenders, (
        "workflows run the integration suite without SANITY_REQUIRE_IMAGES=1: "
        + ", ".join(offenders)
    )
