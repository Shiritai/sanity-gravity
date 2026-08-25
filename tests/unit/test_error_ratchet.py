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
import os
from collections import Counter
from pathlib import Path

import pytest

# Source-tree fingerprint: under mutmut the scanned files are the
# generated mutant tree, where every function containing a guarded call
# is cloned once per mutant and the counts multiply. The test executes
# no package code and can never kill a mutant; the real suite always
# runs it.
pytestmark = pytest.mark.skipif(
    "MUTANT_UNDER_TEST" in os.environ,
    reason="source-tree guard is meaningless against mutmut's generated tree",
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SOURCE_ROOTS = ("sanity_gravity", "plugins")

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


class _ExitFinder(ast.NodeVisitor):
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
        self.rel_path = rel_path
        self.scope: list[str] = []
        self.hits: Counter[str] = Counter()

    def _scoped(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = _scoped
    visit_AsyncFunctionDef = _scoped
    visit_ClassDef = _scoped

    def _hit(self) -> None:
        qual = ".".join(self.scope) or "<module>"
        self.hits[f"{self.rel_path}::{qual}"] += 1

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = (
            func.attr if isinstance(func, ast.Attribute)
            else func.id if isinstance(func, ast.Name)
            else None
        )
        if name in self._CALL_NAMES:
            self._hit()
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        exc = node.exc
        target = exc.func if isinstance(exc, ast.Call) else exc
        name = (
            target.attr if isinstance(target, ast.Attribute)
            else getattr(target, "id", None)
        )
        if name == "SystemExit":
            self._hit()
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module in ("sys", "os") and any(
            a.name in self._CALL_NAMES for a in node.names
        ):
            self._hit()
        self.generic_visit(node)


def _source_files():
    for root in _SOURCE_ROOTS:
        yield from sorted((_REPO_ROOT / root).rglob("*.py"))


def _parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"))


def _scan_exits() -> Counter[str]:
    found: Counter[str] = Counter()
    for path in _source_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel in _ALLOWED:
            continue
        finder = _ExitFinder(rel)
        finder.visit(_parse(path))
        found.update(finder.hits)
    return found


def _scan_systemexit_excepts() -> Counter[str]:
    """Count except handlers whose type mentions SystemExit, per file."""
    found: Counter[str] = Counter()
    for path in _source_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for node in ast.walk(_parse(path)):
            if not isinstance(node, ast.ExceptHandler) or node.type is None:
                continue
            elts = (
                node.type.elts if isinstance(node.type, ast.Tuple)
                else [node.type]
            )
            names = {
                e.attr if isinstance(e, ast.Attribute)
                else getattr(e, "id", None)
                for e in elts
            }
            if "SystemExit" in names:
                found[rel] += 1
    return found


def _scan_verb_subprocess_imports() -> set[str]:
    found: set[str] = set()
    verbs = _REPO_ROOT / "sanity_gravity" / "verbs"
    for path in sorted(verbs.rglob("*.py")):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for node in ast.walk(_parse(path)):
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


def _stale_entries(
    frozen: dict[str, int], found: Counter[str]
) -> dict[str, tuple[int, int]]:
    """Frozen entries the tree no longer justifies: {key: (frozen, actual)}.

    The half of a ratchet everyone forgets. An entry whose debt was paid
    but never deleted keeps a slot open at the old count, so the site can
    silently regrow all the way back up to it -- the list stops being a
    ceiling and becomes a quota.
    """
    return {
        key: (n, found.get(key, 0))
        for key, n in frozen.items()
        if found.get(key, 0) < n
    }


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
    """
    assert _stale_entries(frozen, Counter(found)) == expected


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
    stale = _stale_entries(KNOWN_SYS_EXIT_SITES, found)
    assert not stale, (
        "these sites no longer have (as many) sys.exit calls -- update "
        f"KNOWN_SYS_EXIT_SITES to match, entries are (frozen, actual): {stale}"
    )


def test_no_systemexit_in_except_clauses():
    found = _scan_systemexit_excepts()
    new = {
        k: n for k, n in found.items()
        if n > KNOWN_SYSTEMEXIT_EXCEPT_FILES.get(k, 0)
    }
    stale = _stale_entries(KNOWN_SYSTEMEXIT_EXCEPT_FILES, found)
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
    for path in _source_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel in _RUN_COMMAND_ALLOWED:
            continue
        for node in ast.walk(_parse(path)):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "run_command"
            ):
                offenders.append(f"{rel}:{node.lineno} (def)")
            elif isinstance(node, ast.Call):
                f = node.func
                name = (
                    f.attr if isinstance(f, ast.Attribute)
                    else getattr(f, "id", None)
                )
                if name == "run_command":
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
    src = (_REPO_ROOT / "sanity_gravity" / "cli" / "main.py").read_text()
    tree = ast.parse(src)
    offenders = [
        h.lineno
        for h in ast.walk(tree)
        if isinstance(h, ast.ExceptHandler)
        and (
            h.type is None
            or (
                isinstance(h.type, ast.Name)
                and h.type.id in {"Exception", "BaseException"}
            )
        )
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
