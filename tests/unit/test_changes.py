"""needs_images: a change builds images unless every path is docs-only."""
from __future__ import annotations

import subprocess
import sys

import pytest

from sanity_gravity.core.changes import needs_images
from tests.support import REPO_ROOT

DOCS_ONLY = (
    "README.md",
    "README_ja.md",
    "README_zh-TW.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "SECURITY.md",
    "assets/logo.png",
    "docs/tags.md",
    "docs/a/b/c.md",
)

NEEDS_IMAGES = (
    "sanity-cli",
    "pyproject.toml",
    "sanity_gravity/core/changes.py",
    "plugins/agents/ag/Dockerfile",
    "sandbox/Dockerfile.base",
    ".github/workflows/ci-pr.yml",
    "tests/unit/test_changes.py",
    # Patterns are anchored at the repo root, as in GitHub's filters: a
    # README inside a build context is part of that image.
    "plugins/agents/ag/README.md",
    "sandbox/rootfs/usr/share/doc/README.md",
    # "*" stops at "/", and a pattern names a whole path, not a prefix.
    "README_ja/notes.md",
    "README.md.orig",
    "LICENSE.txt",
    "docsx/tags.md",
)


@pytest.mark.parametrize("path", DOCS_ONLY)
def test_a_docs_only_path_needs_no_images(path):
    assert needs_images([path]) is False


@pytest.mark.parametrize("path", NEEDS_IMAGES)
def test_any_other_path_needs_images(path):
    assert needs_images([path]) is True


def test_one_non_docs_path_among_docs_needs_images():
    assert needs_images([*DOCS_ONLY, "plugins/agents/ag/Dockerfile"]) is True


def test_no_paths_needs_images():
    """An empty diff more likely means a wrong range than an empty PR."""
    assert needs_images([]) is True


@pytest.mark.parametrize(
    ("stdin", "stdout"),
    [
        ("docs/tags.md\nREADME.md\n", "false\n"),
        ("docs/tags.md\nsanity-cli\n", "true\n"),
        ("\n", "true\n"),
    ],
    ids=["docs-only", "code", "empty"],
)
def test_module_entry_point_as_ci_calls_it(stdin, stdout):
    proc = subprocess.run(
        (sys.executable, "-m", "sanity_gravity.core.changes"),
        input=stdin, cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )
    assert proc.stdout == stdout
