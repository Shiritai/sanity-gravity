"""Matrix guards: capacity and coverage assumptions as executable contracts.

The CI/publish surface is sized implicitly (workflow timeouts, runner
pools, GHCR package count) against the official matrix, and nothing in
the diff of a matrix-widening change touches .github/. These guards make
the three implicit rules fail closed on a developer laptop instead:

1. The official matrix has a budgeted ceiling - raising it is a
   deliberate, reviewable act, not a side effect of a manifest edit.
2. A new official tag ships with an integration test declaring it via
   ``requires_image``, or is explicitly declared as debt (a list that
   may only shrink). The marker is the coverage record: substring
   grepping used to count docstrings and mock strings as coverage.
3. Tag-list filters in tests must parse tags, not prefix-match them:
   ``t.startswith("ag-")`` silently stops matching the moment another
   dimension prefixes the tag, so invariants keep passing while
   covering ever less of the matrix.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from sanity_gravity.core.registry import OFFICIAL_TAGS, VALID_TAGS
from tests.support import REPO_ROOT, py_files, walk

_TESTS_DIR = REPO_ROOT / "tests"
_INTEGRATION_DIR = _TESTS_DIR / "integration"
_PRECONDITION_MARKS = frozenset({"requires_image", "requires_docker", "no_image"})

# Raising this ceiling is a CI budget review, not a formality: build all
# runs the whole matrix serially on one runner per arch under
# .github/workflows/_build.yml's timeout-minutes, and every tag adds
# publish/scan/pull fan-out (2 arches each). Re-derive the timeout math
# from the latest release run before bumping.
MAX_OFFICIAL_TAGS = 19

# Official tags no integration test declares via requires_image, frozen
# 2026-08 when the guard landed (re-verified against marker truth when
# the evidence moved from substring grep to markers - same 13 entries).
# This list may only SHRINK: add a test that boots the tag and declares
# it, then delete its entry. New official tags must not join it.
KNOWN_UNTESTED_OFFICIAL_TAGS = frozenset({
    "agy-none-ssh", "agy-xfce-kasm", "agy-xfce-ssh", "agy-xfce-vnc",
    "cc-xfce-kasm", "cc-xfce-ssh", "cc-xfce-vnc",
    "cx-xfce-kasm", "cx-xfce-ssh", "cx-xfce-vnc",
    "oc-xfce-kasm", "oc-xfce-ssh", "oc-xfce-vnc",
})


def test_official_matrix_within_ci_budget():
    assert len(OFFICIAL_TAGS) <= MAX_OFFICIAL_TAGS, (
        f"OFFICIAL_TAGS grew to {len(OFFICIAL_TAGS)} (budget: "
        f"{MAX_OFFICIAL_TAGS}). This multiplies every CI/publish surface "
        "(build-all steps, Trivy scans, GHCR packages, pull-all). Re-derive "
        "the CI budget (workflow timeouts, runner fan-out) and raise "
        "MAX_OFFICIAL_TAGS in the same change - or keep the new plugin at "
        'tier = "community" until it is tested and budgeted.'
    )


def _mark_name(node: ast.AST) -> str | None:
    """``pytest.mark.foo`` -> "foo"; anything else -> None."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute):
        if node.value.attr == "mark":
            return node.attr
    return None


def _integration_modules():
    """Every integration test module, as ``(path, rel)``. Recursive
    where the original scan was flat, which cannot change the answer:
    test_no_test_files_outside_the_two_suites already forbids a
    ``test_*.py`` below tests/integration/."""
    return py_files(_INTEGRATION_DIR, pattern="test_*.py")


def _declared(path: Path) -> tuple[set[str], set[str]]:
    """Return (marker names, requires_image tags) declared in one module.

    Static AST rather than a pytest collection hook: the guard must tell
    the truth when someone runs `pytest tests/unit` alone, and it must
    not need a docker daemon to answer a question about source text.
    """
    marks: set[str] = set()
    tags: set[str] = set()
    for node in walk(path):
        if isinstance(node, ast.Attribute):          # bare `pytest.mark.requires_docker`
            name = _mark_name(node)
            if name:
                marks.add(name)
        elif isinstance(node, ast.Call):             # `pytest.mark.requires_image(...)`
            name = _mark_name(node.func)
            if name != "requires_image":
                continue
            for arg in node.args:
                assert isinstance(arg, ast.Constant) and isinstance(arg.value, str), (
                    f"{path.name}: requires_image() takes literal tag strings; a "
                    "computed argument is invisible to the coverage ratchet"
                )
                tags.add(arg.value)
    return marks, tags


def test_every_integration_file_declares_a_precondition():
    """A tests/integration file must say what it needs from the outside world.

    Without this, "forgot the guard" and "genuinely needs nothing" are
    indistinguishable in a diff - which is how 17 of 20 files ended up
    reporting a missing image as RuntimeError instead of a skip.
    """
    undeclared = [
        rel for path, rel in _integration_modules()
        if not (_declared(path)[0] & _PRECONDITION_MARKS)
    ]
    assert not undeclared, (
        "integration tests must declare a precondition with one of "
        f"{sorted(_PRECONDITION_MARKS)} (see tests/conftest.py):\n  "
        + "\n  ".join(undeclared)
    )


def test_no_test_files_outside_the_two_suites():
    """``testpaths = tests`` collects the whole tree, so a test module
    parked outside tests/unit and tests/integration joins every full
    run while escaping both suites' contracts: the marker meta-guards
    above scan only tests/integration, and the hermeticity conventions
    bind only tests/unit. Every test module must live in exactly one of
    the two suites."""
    allowed = {_TESTS_DIR / "unit", _INTEGRATION_DIR}
    strays = [
        rel for path, rel in py_files(_TESTS_DIR, pattern="test_*.py")
        if path.parent not in allowed
    ]
    assert not strays, (
        "test modules outside tests/unit and tests/integration are "
        "collected by testpaths=tests but guarded by neither suite's "
        f"contract - move them into a suite: {strays}"
    )


def _marker_coverage() -> set[str]:
    """Tags an integration test actually declares it needs an image for."""
    covered: set[str] = set()
    for path, _ in _integration_modules():
        covered |= _declared(path)[1]
    return covered


def test_official_tags_are_exercised_or_declared_debt():
    referenced = _marker_coverage()

    # A typo'd tag is not coverage, and it is not silent either.
    unknown = referenced - set(VALID_TAGS)
    assert not unknown, (
        f"requires_image() names tags that do not exist: {sorted(unknown)}. "
        "The marker is the coverage record; a typo here used to read as "
        "'this tag is untested' with no other symptom."
    )

    missing = set(OFFICIAL_TAGS) - referenced - KNOWN_UNTESTED_OFFICIAL_TAGS
    assert not missing, (
        f"official tags with no integration test: {sorted(missing)}. Add a "
        "test that boots the image and declare it with "
        '@pytest.mark.requires_image("<tag>") - promoting a tag to the '
        "official matrix means promising it works."
    )

    # Ratchet: entries that gained coverage or left the official matrix
    # must be removed so the debt list only ever shrinks.
    stale = KNOWN_UNTESTED_OFFICIAL_TAGS - set(OFFICIAL_TAGS)
    assert not stale, f"debt entries no longer official - delete them: {sorted(stale)}"
    now_covered = KNOWN_UNTESTED_OFFICIAL_TAGS & referenced
    assert not now_covered, (
        f"debt entries now covered by an integration test - delete them: "
        f"{sorted(now_covered)}"
    )


def test_no_prefix_matching_on_tag_lists():
    """Filters over VALID_TAGS/OFFICIAL_TAGS must parse, not prefix-match.

    Every .py under tests/, not only test modules: tests/support.py and
    tests/utils.py are exactly where a shared helper would hide such a
    filter from a test-file-only scan.
    """
    offenders = []
    for path, rel in py_files(_TESTS_DIR):
        if path.name == Path(__file__).name:
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if "startswith(" in line and re.search(r"\b(VALID|OFFICIAL)_TAGS\b", line):
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert not offenders, (
        "prefix-matching a tag list goes silently blind when a new "
        "dimension prefixes the tag; filter via resolve_tag(t).<dim> instead:\n"
        + "\n".join(offenders)
    )
