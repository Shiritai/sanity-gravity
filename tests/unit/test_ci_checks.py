"""Required status checks: the names branch protection on main waits for.

Branch protection matches checks by name, and GitHub derives the names
from workflow structure: a top-level job reports its ``name:`` (else its
id), a job in a reusable workflow reports ``<caller id> / <called
name>``, and a matrix appends ``(<value>)``. A rename, a matrix, a
reusable-workflow wrapper or an ``if:`` on a caller job makes a required
check stop reporting, and so does a trigger path filter on a docs-only
PR; the PR then waits on it forever while every visible check is green.
Nothing in the YAML fails when that happens, so these guards pin the
shape that produces the names.
"""
from __future__ import annotations

import pytest
import yaml

from sanity_gravity.core.changes import DOCS_ONLY_PATTERNS
from tests.support import REPO_ROOT

_WORKFLOWS = REPO_ROOT / ".github" / "workflows"

#: Kept by hand in main's branch protection; change both together.
REQUIRED_CHECKS = frozenset({
    "hermetic",
    "verify-x64 / build-and-verify",
    "verify-arm64 / build-and-verify",
})

_PATH_FILTERS = ("paths", "paths-ignore")


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(wf) -> dict:
    # YAML 1.1 reads the bare key ``on`` as the boolean True.
    on = wf.get("on", wf.get(True))
    if isinstance(on, str):
        on = [on]
    if isinstance(on, list):
        return {event: {} for event in on}
    return {event: config or {} for event, config in on.items()}


def _producers(event: str) -> dict[str, list[tuple[str, dict, dict]]]:
    """Check name -> ``(workflow file, its triggers, job)`` for every job
    that reports a check on ``event``, a reusable workflow's jobs under
    the name GitHub gives them."""
    found: dict[str, list[tuple[str, dict, dict]]] = {}
    for path in sorted(_WORKFLOWS.glob("*.yml")):
        wf = _load(path)
        triggers = _triggers(wf)
        if event not in triggers:
            continue
        for job_id, job in wf["jobs"].items():
            caller = job.get("name", job_id)
            if "uses" in job:
                called = _load(REPO_ROOT / job["uses"])
                for called_id, called_job in called["jobs"].items():
                    name = f"{caller} / {called_job.get('name', called_id)}"
                    found.setdefault(name, []).append((path.name, triggers, called_job))
            else:
                found.setdefault(caller, []).append((path.name, triggers, job))
    return found


@pytest.mark.parametrize("check", sorted(REQUIRED_CHECKS))
def test_every_pr_reports_the_required_check_once(check):
    producers = _producers("pull_request").get(check, [])
    assert len(producers) == 1, (
        f"required check {check!r} must come from exactly one job on "
        f"pull_request, found {[wf for wf, _, _ in producers]}"
    )
    wf, triggers, job = producers[0]
    pr = triggers["pull_request"]
    assert not any(key in pr for key in _PATH_FILTERS), (
        f"{wf}: a path filter on pull_request leaves {check!r} Pending "
        "on the PRs it filters out; skip the job with if: instead"
    )
    assert "main" in pr.get("branches", ["main"]), wf
    assert "matrix" not in job.get("strategy", {}), (
        f"{wf}: a matrix renames {check!r} to '{check} (<value>)'"
    )


def test_hermetic_runs_on_every_push_to_main():
    """The maintainer pushes straight to main, docs-only pushes included,
    and ci-release.yml skips those - so the hermetic check needs its own
    unfiltered push trigger."""
    producers = _producers("push").get("hermetic", [])
    assert len(producers) == 1, producers
    wf, triggers, job = producers[0]
    push = triggers["push"]
    assert "main" in push.get("branches", ["main"]), wf
    assert not any(key in push for key in _PATH_FILTERS), wf
    assert "if" not in job, f"{wf}: an if: on the hermetic job can skip it"


def test_hermetic_job_runs_lint_and_the_hermetic_suite():
    ((wf, _, job),) = _producers("pull_request")["hermetic"]
    runs = "\n".join(step.get("run", "") for step in job["steps"])
    for command in ("ruff check .", "lint-imports", 'pytest -m "not requires_docker"'):
        assert command in runs, f"{wf}: hermetic job no longer runs {command!r}"


def test_hermetic_job_never_declares_a_disposable_host():
    """Tests marked mutates_host change the machine they run on. The
    hermetic job is the one that runs on every PR, so it must keep them
    skipped; only the image jobs, which start from a fresh VM, opt in."""
    ((wf, _, job),) = _producers("pull_request")["hermetic"]
    workflow = _load(_WORKFLOWS / wf)
    envs = [workflow.get("env", {}), job.get("env", {})]
    envs += [step.get("env", {}) for step in job["steps"]]
    assert not any("SANITY_DISPOSABLE_HOST" in env for env in envs), wf


def test_verify_checks_skip_inside_the_called_workflow():
    """A caller job skipped by if: never expands its reusable workflow,
    so ``verify-* / build-and-verify`` would not report at all; the skip
    for docs-only changes must sit on the called job."""
    ci_pr = _load(_WORKFLOWS / "ci-pr.yml")
    for caller in ("verify-x64", "verify-arm64"):
        job = ci_pr["jobs"][caller]
        assert job["uses"] == "./.github/workflows/_build-and-verify.yml", caller
        assert "if" not in job, f"ci-pr.yml: {caller} must not carry an if:"
        assert "needs_images" in job["with"], caller
    called = _load(_WORKFLOWS / "_build-and-verify.yml")["jobs"]["build-and-verify"]
    assert "inputs.needs_images" in called["if"]


def test_setup_job_classifies_changes_with_the_tested_module():
    text = (_WORKFLOWS / "ci-pr.yml").read_text(encoding="utf-8")
    assert "python3 -m sanity_gravity.core.changes" in text


def test_release_trigger_ignores_the_same_docs_only_paths():
    """ci-release.yml still filters its push trigger by path; its list and
    the PR classifier's must not drift apart."""
    push = _triggers(_load(_WORKFLOWS / "ci-release.yml"))["push"]
    assert sorted(push["paths-ignore"]) == sorted(DOCS_ONLY_PATTERNS)


def test_scheduled_build_verifies_both_arches_without_publishing():
    """The scheduled build is the only image check that runs while nobody
    pushes. It must run the PR's build, tests and Trivy gate on both
    arches and hold no permission that could reach the registry."""
    wf = _load(_WORKFLOWS / "scheduled-build.yml")
    triggers = _triggers(wf)
    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert triggers["schedule"], "scheduled-build.yml: no cron entry"
    assert wf["permissions"] == {"contents": "read"}
    called = {job["with"]["arch"]: job for job in wf["jobs"].values() if "uses" in job}
    assert set(called) == {"amd64", "arm64"}
    for arch, job in called.items():
        assert job["uses"] == "./.github/workflows/_build-and-verify.yml", arch
        assert job["with"]["needs_images"] is True, arch
        assert "permissions" not in job, arch
