"""Shared machinery for the guards that read the repo instead of running it.

The meta layer of this suite - the exit ratchet, the naming guard, the
matrix guards, the docs/packaging/architecture contracts - does not
import the package under test; it reads the tree as text or AST. Six of
those modules had independently derived the same four things: where the
repo root is, how to walk a tree of .py files, how to key a hit by its
enclosing qualname, and what "this frozen list may only shrink" means.
Four hand-rolled copies of one scan is four chances for one copy to go
quietly blind - the one failure mode a guard cannot survive, because a
guard that stops seeing things still passes.

Not tests/conftest.py: conftest is itself under test (
test_requires_image_marker.py replays its source inside a pytester
session), so it must stay importable standing alone. Not
test_support.py: test_matrix_guards requires every ``test_*.py`` under
tests/ to live in one of the two suites, and this belongs to neither.
"""
from __future__ import annotations

import ast
import os
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import TypeVar

import pytest

#: ``<root>/tests/support.py`` -> ``<root>``. Derived once: every guard
#: that recomputed it hard-coded its own distance to the root, which is
#: correct until a file moves one directory and then scans nothing.
REPO_ROOT = Path(__file__).resolve().parent.parent
PKG_ROOT = REPO_ROOT / "sanity_gravity"

#: Under mutmut the scanned files are the generated mutant tree, where
#: every guarded function is cloned once per mutant and per-site counts
#: multiply. These guards execute no package code and can never kill a
#: mutant, so skipping them there loses nothing; the real suite always
#: runs them.
source_tree_guard = pytest.mark.skipif(
    "MUTANT_UNDER_TEST" in os.environ,
    reason="source-tree guard is meaningless against mutmut's generated tree",
)


def py_files(*roots: Path, pattern: str = "*.py") -> Iterator[tuple[Path, str]]:
    """``(path, repo-relative posix path)`` for each match, root by root.

    The relative path is yielded rather than left to the caller because
    it is what every allowlist, ratchet key and failure message keys on.
    Sorted within each root so failures list offenders stably.
    """
    for root in roots:
        for path in sorted(root.rglob(pattern)):
            yield path, path.relative_to(REPO_ROOT).as_posix()


def parse(path: Path) -> ast.Module:
    """One file's AST, tagged with its path for parse errors."""
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def walk(path: Path) -> Iterator[ast.AST]:
    """Every node in one file, for guards that need no scope tracking."""
    return ast.walk(parse(path))


def node_name(node: ast.AST | None) -> str | None:
    """The trailing name a node spells - ``sys.exit`` and bare ``exit``
    both answer "exit" - else None.

    Matching the trailing name is what lets a guard see through import
    aliases without tracking them: an alias is not a different act.
    """
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


class QualnameVisitor(ast.NodeVisitor):
    """Visitor tracking the enclosing def/class chain, so ratchet keys
    can be ``<file>::<qualname>`` and not line numbers: an unrelated edit
    above a frozen site must not churn the debt list."""

    def __init__(self) -> None:
        self.scope: list[str] = []

    @property
    def qualname(self) -> str:
        return ".".join(self.scope) or "<module>"

    def _scoped(self, node) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = _scoped
    visit_AsyncFunctionDef = _scoped
    visit_ClassDef = _scoped


_Amount = TypeVar("_Amount")


def uncovered(
    claim: Mapping[str, _Amount],
    actual: Mapping[str, _Amount],
    *,
    empty: _Amount = 0,
) -> dict[str, tuple[_Amount, _Amount]]:
    """Entries of ``claim`` that ``actual`` does not account for, as
    ``{key: (claimed, actual)}``.

    One primitive serves both halves of a frozen ratchet, which are the
    same question asked in opposite directions:

        uncovered(found, frozen)  -> the ceiling: new or regrown debt
        uncovered(frozen, found)  -> the stale half everyone forgets, an
                                     entry whose debt was paid but never
                                     deleted keeps its slot open at the
                                     old count, so the site can regrow
                                     back up to it and the list stops
                                     being a ceiling and becomes a quota

    Keeping the directions distinct matters as much as sharing the
    comparison: regrowth is deliberately NOT stale, and conflating the
    two would let each hide the other.

    ``>=`` carries both value shapes this repo freezes - "at least as
    many" for counts, "still renders all of them" for family sets.
    Set-shaped callers pass ``empty=frozenset()``, since the default
    zero cannot be compared against a set.
    """
    return {
        key: (want, actual.get(key, empty))
        for key, want in claim.items()
        if not actual.get(key, empty) >= want
    }
# scratch
