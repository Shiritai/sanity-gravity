"""Docs contract: the entry docs must not resurrect the variant era.

CONTRIBUTING.md and the READMEs are the first files a contributor
reads, and they went stale once already: CONTRIBUTING kept pointing at
`Dockerfile.<variant>`, `sandbox/variants/`, `unittest discover`, and
Python 3.7 long after the plugin tree, pytest, and the 3.11 floor
replaced them - and the identical "Python 3.7+" claim lived on in all
three READMEs after CONTRIBUTING was fixed. Prose has no compiler, so
the load-bearing entry points are pinned here instead: the known-stale
strings must never come back in any of these files, and the anchors
the current workflow depends on must stay present.
"""
from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CONTRIBUTING = _REPO_ROOT / "CONTRIBUTING.md"
# Every reader-facing entry doc: the translations rot at the same rate
# as the English one, so they are scanned as one set.
_READMES = tuple(sorted(_REPO_ROOT.glob("README*.md")))

# Each entry names a concept the repo no longer has. If one reappears,
# either the doc regressed or the concept returned - both deserve a red.
_STALE = (
    "Dockerfile.<variant>",   # variant model -> plugins/<kind>/<slug>/
    "unittest discover",      # unittest -> pytest
    "sandbox/variants/",      # directory does not exist
    "Python 3.7",             # requires-python = ">=3.11" (tomllib)
)

# Entry points the contributor workflow depends on. Substring checks on
# purpose: the doc may rephrase around them, but losing one means a
# whole section (setup, test preconditions, matrix budget) went missing.
_ANCHORS = (
    'pip install -e',         # editable install; CI installs the same way
    "requires_image",         # integration precondition marker
    "MAX_OFFICIAL_TAGS",      # the matrix budget is documented, not folklore
    "One PR, one base",       # issue-first / no-stacking policy section
)


def test_contributing_has_no_known_stale_strings():
    text = _CONTRIBUTING.read_text()
    present = [s for s in _STALE if s in text]
    assert not present, (
        f"CONTRIBUTING.md contains stale strings {present}; these refer to "
        "mechanisms the repo no longer has (see this test's module docstring)"
    )


def test_readmes_have_no_known_stale_strings():
    """Same rot, one file over: the guard used to watch CONTRIBUTING
    alone while all three READMEs still promised Python 3.7+."""
    assert _READMES, "README*.md glob found nothing; the repo moved under us"
    offenders = {
        readme.name: [s for s in _STALE if s in readme.read_text()]
        for readme in _READMES
    }
    offenders = {name: hits for name, hits in offenders.items() if hits}
    assert not offenders, (
        f"stale strings survive in {offenders}; these refer to mechanisms "
        "the repo no longer has (see this test's module docstring)"
    )


def test_contributing_keeps_load_bearing_anchors():
    text = _CONTRIBUTING.read_text()
    missing = [a for a in _ANCHORS if a not in text]
    assert not missing, (
        f"CONTRIBUTING.md lost load-bearing anchors {missing}; the setup, "
        "test-precondition, or matrix-budget guidance went missing"
    )
