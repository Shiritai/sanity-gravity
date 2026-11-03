"""Which CI work a set of changed paths calls for.

The PR pipeline cannot skip a docs-only change with a trigger filter: a
workflow skipped by ``paths-ignore`` reports none of its checks, so the
required ones stay Pending forever, while a job skipped by ``if:``
reports Success. CI's setup job therefore runs ``git diff`` and asks
this module whether the change needs images, and the answer gates the
build job, not the trigger.

Pure on purpose: paths in, answer out, so the rule is unit-tested with
no git, no repo and no runner.
"""
from __future__ import annotations

import re
import sys
from collections.abc import Iterable

#: Paths no image build or integration test reads, in GitHub's filter
#: syntax (``*`` stops at ``/``, ``**`` does not) so that ci-release.yml's
#: ``paths-ignore`` can be checked against this tuple verbatim.
DOCS_ONLY_PATTERNS = (
    "README.md",
    "README_*.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "SECURITY.md",
    "assets/**",
    "docs/**",
)


def _glob(pattern: str) -> re.Pattern[str]:
    parts = re.split(r"(\*\*|\*)", pattern)
    return re.compile("".join(
        ".*" if part == "**" else "[^/]*" if part == "*" else re.escape(part)
        for part in parts
    ))


_DOCS_ONLY = tuple(_glob(p) for p in DOCS_ONLY_PATTERNS)


def _is_docs_only(path: str) -> bool:
    return any(rx.fullmatch(path) for rx in _DOCS_ONLY)


def needs_images(paths: Iterable[str]) -> bool:
    """False only when there are changed paths and every one is docs-only.

    No paths at all reads as "unknown", not as "docs-only": a wrong diff
    range must cost a redundant build, never a PR whose images were not
    built.
    """
    paths = list(paths)
    return not paths or not all(_is_docs_only(p) for p in paths)


if __name__ == "__main__":
    # CI entry point: changed paths on stdin, one per line (git diff
    # --name-only); prints "true" or "false" for a job output.
    changed = [line.rstrip("\r\n") for line in sys.stdin]
    changed = [path for path in changed if path]
    print("true" if needs_images(changed) else "false")
