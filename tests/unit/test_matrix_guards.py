"""Matrix guards: capacity and coverage assumptions as executable contracts.

The CI/publish surface is sized implicitly (workflow timeouts, runner
pools, GHCR package count) against the official matrix, and nothing in
the diff of a matrix-widening change touches .github/. These guards make
the three implicit rules fail closed on a developer laptop instead:

1. The official matrix has a budgeted ceiling - raising it is a
   deliberate, reviewable act, not a side effect of a manifest edit.
2. A new official tag ships with an integration reference, or is
   explicitly declared as debt (a list that may only shrink).
3. Tag-list filters in tests must parse tags, not prefix-match them:
   ``t.startswith("ag-")`` silently stops matching the moment another
   dimension prefixes the tag, so invariants keep passing while
   covering ever less of the matrix.
"""
from __future__ import annotations

import re
from pathlib import Path

from sanity_gravity.cli.registry import OFFICIAL_TAGS

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Raising this ceiling is a CI budget review, not a formality: build all
# runs the whole matrix serially on one runner per arch under
# .github/workflows/_build.yml's timeout-minutes, and every tag adds
# publish/scan/pull fan-out (2 arches each). Re-derive the timeout math
# from the latest release run before bumping.
MAX_OFFICIAL_TAGS = 19

# Official tags with no integration-test reference, frozen 2026-08 when
# this guard landed. This list may only SHRINK: add a test that boots
# the tag, then delete its entry. New official tags must not join it.
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


def _integration_sources() -> str:
    parts = [(_REPO_ROOT / "tests" / "conftest.py").read_text()]
    for p in sorted((_REPO_ROOT / "tests" / "integration").glob("*.py")):
        parts.append(p.read_text())
    extra = _REPO_ROOT / "tests" / "test_volume_isolation.py"
    if extra.exists():
        parts.append(extra.read_text())
    return "\n".join(parts)


def test_official_tags_are_exercised_or_declared_debt():
    src = _integration_sources()
    referenced = {t for t in OFFICIAL_TAGS if t in src}

    missing = set(OFFICIAL_TAGS) - referenced - KNOWN_UNTESTED_OFFICIAL_TAGS
    assert not missing, (
        f"official tags with no integration-test reference: {sorted(missing)}. "
        "Add a test that exercises the image (see test_cx_agent.py for the "
        "skipif-guarded pattern) - promoting a tag to the official matrix "
        "means promising it works."
    )

    # Ratchet: entries that gained coverage or left the official matrix
    # must be removed so the debt list only ever shrinks.
    stale = KNOWN_UNTESTED_OFFICIAL_TAGS - set(OFFICIAL_TAGS)
    assert not stale, f"debt entries no longer official - delete them: {sorted(stale)}"
    now_covered = KNOWN_UNTESTED_OFFICIAL_TAGS & referenced
    assert not now_covered, (
        f"debt entries now referenced by integration tests - delete them: "
        f"{sorted(now_covered)}"
    )


def test_no_prefix_matching_on_tag_lists():
    """Filters over VALID_TAGS/OFFICIAL_TAGS must parse, not prefix-match."""
    offenders = []
    for p in sorted((_REPO_ROOT / "tests").rglob("*.py")):
        if p.name == Path(__file__).name:
            continue
        for lineno, line in enumerate(p.read_text().splitlines(), 1):
            if "startswith(" in line and re.search(r"\b(VALID|OFFICIAL)_TAGS\b", line):
                offenders.append(
                    f"{p.relative_to(_REPO_ROOT)}:{lineno}: {line.strip()}"
                )
    assert not offenders, (
        "prefix-matching a tag list goes silently blind when a new "
        "dimension prefixes the tag; filter via parse_tag(t) instead:\n"
        + "\n".join(offenders)
    )
