"""Packaging contract: dependencies have one source of truth.

Runtime deps live in [project.dependencies]; tool deps live in extras
("test" for the suite, "lint" for ruff). CI must install through the
package (-e ".[<extra>]") so a dependency added to pyproject.toml
reaches CI without editing YAML. The workflow steps that run the
integration suite are pinned here too: their environment is what makes
the suite's skips and opt-ins mean what they say.
"""
import tomllib

import yaml

from tests.support import REPO_ROOT


def _extras() -> dict[str, list[str]]:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
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
    for wf in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        for lineno, line in enumerate(wf.read_text().splitlines(), 1):
            if "pip install" not in line or "--upgrade pip" in line:
                continue
            if not any(form in line for form in allowed):
                offenders.append(f"{wf.name}:{lineno}: {line.strip()}")
    assert not offenders, (
        "workflows must install deps via 'pip install -e \".[<extra>]\"' "
        f"for a declared extra {sorted(_extras())}:\n" + "\n".join(offenders)
    )


def _suite_steps() -> list[tuple[str, dict]]:
    """``(workflow: step name, effective env)`` for every step that runs
    ./sanity-cli test, env merged the way Actions does: workflow, then
    job, then step."""
    found = []
    for wf in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        data = yaml.safe_load(wf.read_text())
        for job in data["jobs"].values():
            for step in job.get("steps", []):
                if "sanity-cli test" in step.get("run", ""):
                    env = {**data.get("env", {}), **job.get("env", {}), **step.get("env", {})}
                    found.append((f"{wf.name}: {step.get('name', '<unnamed>')}", env))
    assert found, "no workflow step runs ./sanity-cli test - the guards below went blind"
    return found


def test_workflows_running_the_suite_require_images():
    """Any workflow step that runs ./sanity-cli test must set
    SANITY_REQUIRE_IMAGES: a suite that may skip is a suite that may lie
    (a mistyped build/pull loop would otherwise read as all-green)."""
    offenders = [
        step for step, env in _suite_steps() if env.get("SANITY_REQUIRE_IMAGES") != "1"
    ]
    assert not offenders, (
        "steps run the integration suite without SANITY_REQUIRE_IMAGES=1: "
        + ", ".join(offenders)
    )


def test_workflows_running_the_suite_declare_a_disposable_host():
    """Any workflow step that runs ./sanity-cli test must set
    SANITY_DISPOSABLE_HOST: a GitHub-hosted runner is a fresh VM per job,
    the one place the mutates_host tests may change the machine, and
    without the variable they skip there too and never run anywhere."""
    offenders = [
        step for step, env in _suite_steps() if env.get("SANITY_DISPOSABLE_HOST") != "1"
    ]
    assert not offenders, (
        "steps run the integration suite without SANITY_DISPOSABLE_HOST=1: "
        + ", ".join(offenders)
    )
