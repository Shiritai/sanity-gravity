"""Ratchet: sys.exit belongs to the process boundary, nowhere else.

A library that calls ``sys.exit`` has decided the fate of a process it
does not own. This guard freezes today's offender list and lets it only
SHRINK. Adding a site fails the build; removing one and forgetting to
delete its entry also fails, so the debt list cannot rot.

Why AST and not grep: ``verbs/upgrade.py`` has the literal text
``sys.exit`` inside a docstring (it documents that run_step deliberately
does NOT exit). A textual guard would count it, and would go red the day
someone rewords that comment. We count call, raise-SystemExit, and
exit-importing nodes.

Why "only cli/main.py" and not "outside cli/": the single worst offender
was ``cli/io.py::run_command`` -- a library helper imported by nine verb
modules that happened to live under cli/. A directory-level allowance
would have exempted precisely the site this rule existed to kill. All
three frozen debt lists have since been paid down to their floors.
"""
from __future__ import annotations

import ast
from collections import Counter

import pytest

from tests.support import (
    PKG_ROOT,
    REPO_ROOT,
    QualnameVisitor,
    node_name,
    parse,
    py_files,
    source_tree_guard,
    uncovered,
    walk,
)

pytestmark = source_tree_guard

_SOURCE_ROOTS = (PKG_ROOT, REPO_ROOT / "plugins")

# The one legitimate process boundary: the CLI entry point renders a
# SanityError and picks the exit code there, once.
_ALLOWED = {"sanity_gravity/cli/main.py"}

# Frozen 2026-08 at the start of the errors.py migration. Keys are
# ``<posix path>::<enclosing qualname>`` -- deliberately NOT line
# numbers, so an unrelated edit above a site does not churn this list.
# This mapping may only shrink. New entries are never acceptable: raise
# a SanityError subclass and let cli/main.py decide the exit code.
KNOWN_SYS_EXIT_SITES: dict[str, int] = {}

# ``except (..., SystemExit)`` is a fossil of panic-in-library: the
# caller wrote SystemExit down because run_command could end the
# process. Frozen as {file: handler count}; every payoff commit deletes
# some. Zero is the finish line.
KNOWN_SYSTEMEXIT_EXCEPT_FILES: dict[str, int] = {}

# Verb modules that import subprocess directly. After the core/proc
# migration every new side effect goes through core/proc or Actions;
# this seed freezes today's offenders and may only shrink (hand-rolled
# interim version of the import-linter architecture contract).
KNOWN_DIRECT_SUBPROCESS: frozenset[str] = frozenset({
    "sanity_gravity/verbs/ide.py",       # check_call x3 (interactive exec)
    "sanity_gravity/verbs/shell.py",     # interactive docker exec -it
})


class _ExitFinder(QualnameVisitor):
    """Collect process-termination sites keyed by enclosing qualname.

    Four spellings of the same act, each caught at its own node type:
    - ``*.exit(...)`` / ``*._exit(...)`` attribute calls: matching on
      the attribute name catches ``sys.exit``, ``_sys.exit`` (a local
      ``import sys as _sys``), ``os.sys.exit`` and ``os._exit`` without
      tracking import aliases.
    - ``exit(...)`` / ``_exit(...)`` bare-name calls: what a
      ``from sys import exit`` (or the builtin) looks like at the site.
    - ``raise SystemExit(...)`` (bare or called): in CPython this IS
      ``sys.exit(...)``; only the sugar differs.
    - ``from sys import exit`` / ``from os import _exit`` themselves:
      an alias (``as die``) hides the call site, so the import is the
      hit.
    """

    _CALL_NAMES = frozenset({"exit", "_exit"})

    def __init__(self, rel_path: str) -> None:
        super().__init__()
        self.rel_path = rel_path
        self.hits: Counter[str] = Counter()

    def _hit(self) -> None:
        self.hits[f"{self.rel_path}::{self.qualname}"] += 1

    def visit_Call(self, node: ast.Call) -> None:
        if node_name(node.func) in self._CALL_NAMES:
            self._hit()
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        exc = node.exc
        target = exc.func if isinstance(exc, ast.Call) else exc
        if node_name(target) == "SystemExit":
            self._hit()
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module in ("sys", "os") and any(
            a.name in self._CALL_NAMES for a in node.names
        ):
            self._hit()
        self.generic_visit(node)


def _scan_exits() -> Counter[str]:
    found: Counter[str] = Counter()
    for path, rel in py_files(*_SOURCE_ROOTS):
        if rel in _ALLOWED:
            continue
        finder = _ExitFinder(rel)
        finder.visit(parse(path))
        found.update(finder.hits)
    return found


def _scan_systemexit_excepts() -> Counter[str]:
    """Count except handlers whose type mentions SystemExit, per file."""
    found: Counter[str] = Counter()
    for path, rel in py_files(*_SOURCE_ROOTS):
        for node in walk(path):
            if not isinstance(node, ast.ExceptHandler) or node.type is None:
                continue
            elts = (
                node.type.elts if isinstance(node.type, ast.Tuple)
                else [node.type]
            )
            if "SystemExit" in {node_name(e) for e in elts}:
                found[rel] += 1
    return found


def _scan_verb_subprocess_imports() -> set[str]:
    found: set[str] = set()
    for path, rel in py_files(PKG_ROOT / "verbs"):
        for node in walk(path):
            imported = (
                isinstance(node, ast.Import)
                and any(a.name == "subprocess" for a in node.names)
            ) or (
                isinstance(node, ast.ImportFrom)
                and node.module == "subprocess"
            )
            if imported:
                found.add(rel)
                break
    return found


# Every spelling below ends (or can end) the process; the ratchet must
# treat them as one act. Each entry was a real blind spot: the finder
# once keyed solely on ast.Attribute with attr == "exit".
#
# One case per detector branch, because a case that two branches can
# satisfy proves neither. Dropped for that reason:
#   - "aliased sys.exit" (_s.exit(3)): same ast.Attribute branch as
#     sys.exit, which already covers it - the alias never reaches the
#     finder, it is erased by the time this is an AST.
#   - "from sys import exit" followed by exit(2): hit by BOTH the
#     ImportFrom branch and the bare-Name branch, so `sum >= 1` stayed
#     true when either one was deleted. Its two halves are now split
#     into the alias case (ImportFrom alone) and the bare exit() case
#     (Name alone), each of which fails when its branch is removed.
_EXIT_EVASIONS = (
    ("sys.exit", "import sys\ndef f():\n    sys.exit(4)\n"),
    ("raise SystemExit(n)", "def f():\n    raise SystemExit(1)\n"),
    ("raise SystemExit bare", "def f():\n    raise SystemExit\n"),
    ("bare exit() call", "def f():\n    exit(2)\n"),
    ("from sys import exit as alias", "from sys import exit as die\n"),
    ("os._exit", "import os\ndef f():\n    os._exit(1)\n"),
)


@pytest.mark.parametrize("label,src", _EXIT_EVASIONS, ids=[e[0] for e in _EXIT_EVASIONS])
def test_exit_finder_sees_every_equivalent_form(label, src):
    """Guard the guard: sys.exit(n) IS raise SystemExit(n) in CPython,
    os._exit is stronger, and a from-import launders the attribute away.
    A detector that only reads one syntax shape protects a spelling,
    not the invariant."""
    finder = _ExitFinder("synthetic.py")
    finder.visit(ast.parse(src))
    assert sum(finder.hits.values()) >= 1, (
        f"_ExitFinder is blind to: {label}"
    )


_STALE_CASES = [
    ({}, {}, {}),
    ({"a::f": 2}, {"a::f": 2}, {}),
    ({"a::f": 2}, {"a::f": 3}, {}),
    ({"a::f": 2}, {"a::f": 1}, {"a::f": (2, 1)}),
    ({"a::f": 1}, {}, {"a::f": (1, 0)}),
    ({"a::f": 1, "b::g": 1}, {"b::g": 1}, {"a::f": (1, 0)}),
]


@pytest.mark.parametrize(
    "frozen,found,expected", _STALE_CASES,
    ids=["empty", "unchanged", "regrown", "shrunk", "vanished", "mixed"],
)
def test_stale_detector_flags_paid_down_debt(frozen, found, expected):
    """Guard the guard, exactly as the _ExitFinder cases above do.

    Both dicts this detector serves -- KNOWN_SYS_EXIT_SITES and
    KNOWN_SYSTEMEXIT_EXCEPT_FILES -- are now empty, so every live call
    below iterates over nothing and no production change can turn one
    red. Feeding the detector synthetic ledgers is what keeps the
    mechanism honest until the day a new debt list is frozen; without
    it the comparison could be inverted outright and the suite would
    not notice. Regrowth is deliberately NOT stale -- that is the
    ceiling check's job, and conflating the two would let each hide the
    other.

    These ledgers now pin the comparison for the naming guard's
    family-set ratchet too, since both shapes share one ``uncovered``:
    flipping ``>=`` to ``<=``, ``>`` or ``==`` reddens the regrown,
    shrunk, vanished or unchanged case here. That guard's own entries
    match the tree exactly, so equal-vs-equal is all its live data can
    ever ask -- which is to say the set shape had no coverage of this
    direction at all while the comparison was inlined there.
    """
    assert uncovered(frozen, Counter(found)) == expected


def test_no_new_sys_exit_outside_the_cli_boundary():
    found = _scan_exits()
    new = {k: n for k, n in found.items() if k not in KNOWN_SYS_EXIT_SITES}
    grown = {
        k: (KNOWN_SYS_EXIT_SITES[k], n)
        for k, n in found.items()
        if k in KNOWN_SYS_EXIT_SITES and n > KNOWN_SYS_EXIT_SITES[k]
    }
    assert not new, (
        "sys.exit added outside cli/main.py: "
        f"{sorted(new)}\n"
        "Library code must not end the process. Raise a SanityError "
        "subclass (domain/errors.py) with a message + hint; cli/main.py "
        "renders it and picks the exit code."
    )
    assert not grown, (
        f"sys.exit count grew at an existing site: {grown}. "
        "The frozen list may only shrink."
    )
    # Rides along on the scan this test already paid for, rather than
    # standing alone as a second always-green test.
    stale = uncovered(KNOWN_SYS_EXIT_SITES, found)
    assert not stale, (
        "these sites no longer have (as many) sys.exit calls -- update "
        f"KNOWN_SYS_EXIT_SITES to match, entries are (frozen, actual): {stale}"
    )


def test_no_systemexit_in_except_clauses():
    found = _scan_systemexit_excepts()
    new = uncovered(found, KNOWN_SYSTEMEXIT_EXCEPT_FILES)
    stale = uncovered(KNOWN_SYSTEMEXIT_EXCEPT_FILES, found)
    assert not new, (
        f"except (..., SystemExit) added or regrown: {new}. "
        "Nothing in this codebase should raise SystemExit below the CLI "
        "boundary; catch the concrete error instead."
    )
    assert not stale, (
        "fossil except-SystemExit clauses were removed -- shrink "
        f"KNOWN_SYSTEMEXIT_EXCEPT_FILES to match: {stale}"
    )


# The shadow implementation is gone; nothing is allowlisted any more.
_RUN_COMMAND_ALLOWED: set[str] = set()


def test_no_run_command_left():
    """The god-function stays dead: no def or call named run_command.

    core/proc's run/capture/try_run replaced it; a revival under the
    old name would resurrect the str|int union and the buried exit.
    """
    offenders: list[str] = []
    for path, rel in py_files(*_SOURCE_ROOTS):
        if rel in _RUN_COMMAND_ALLOWED:
            continue
        for node in walk(path):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "run_command"
            ):
                offenders.append(f"{rel}:{node.lineno} (def)")
            elif isinstance(node, ast.Call) and node_name(node.func) == "run_command":
                offenders.append(f"{rel}:{node.lineno} (call)")
    assert not offenders, (
        f"run_command lives again at: {offenders}. Use core/proc "
        "(run/capture/try_run/run_shell) instead."
    )


def test_boundary_handler_does_not_swallow_bugs():
    """cli/main.py must not re-grow a blanket ``except Exception``.

    The moment it does, every bug in this tool is rendered as a tidy
    one-liner and the stack frame that names the culprit is gone.
    """
    offenders = [
        h.lineno
        for h in walk(PKG_ROOT / "cli" / "main.py")
        if isinstance(h, ast.ExceptHandler)
        and (h.type is None or node_name(h.type) in {"Exception", "BaseException"})
    ]
    assert not offenders, (
        f"blanket except at cli/main.py:{offenders}. Catch SanityError; "
        "let unexpected exceptions print a traceback."
    )


def test_verbs_do_not_import_subprocess_directly():
    found = _scan_verb_subprocess_imports()
    new = found - KNOWN_DIRECT_SUBPROCESS
    stale = KNOWN_DIRECT_SUBPROCESS - found
    assert not new, (
        f"verb modules newly importing subprocess: {sorted(new)}. "
        "Side effects go through core/proc (run/capture/try_run) or "
        "Actions; verbs do not shell out by hand."
    )
    assert not stale, (
        "verb modules no longer import subprocess -- shrink "
        f"KNOWN_DIRECT_SUBPROCESS: {sorted(stale)}"
    )
