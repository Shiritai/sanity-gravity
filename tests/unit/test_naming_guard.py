"""Naming guard: identity strings render only in domain/naming.py.

Every name derived from a sandbox identity (image, container, env var,
volume, compose file, ghcr ref, layer, backup ref) has exactly one
producer method on :class:`Naming`. A hand-rolled f-string of any of
those shapes anywhere else is naming smuggled past the grammar - it
compiles today and silently diverges the day the grammar moves.

Mechanics mirror test_matrix_guards's frozen ratchet: the debt list may
only SHRINK. The scan walks the AST and inspects ``JoinedStr`` nodes,
so docstrings and comments (e.g. compose/builder.py's Usage example)
are naturally excluded and detection keys on actual interpolation, not
raw text. A ``FormattedValue`` that merely references one of Naming's
prefix constants is substituted with its literal value first: a
constant is just an f-string with extra steps, and borrowing the prefix
to hand-assemble the rest of the name is exactly the smuggling this
guard exists to catch.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PKG_ROOT = _REPO_ROOT / "sanity_gravity"

# The only modules allowed to render identity grammar.
_ALLOWED = {
    "sanity_gravity/domain/naming.py",
    "sanity_gravity/domain/tags.py",
}

# Naming's prefix constants, restated literally: the guard must not
# import them from the module under guard or the two lose independence
# and the guard its bite.
_PREFIX_VALUES = {
    "IMAGE_REPO": "sanity-gravity",
    "IMAGE_PREFIX": "sanity-gravity",
    "VOLUME_PREFIX": "sg",
    "CONFIG_DIR": "config",
    "BACKUP_REPO": "sanity-migrate",
}

# One pattern per identity family, matched against the f-string's
# "shape": constants verbatim, interpolations collapsed to ``{}``.
_FAMILIES = (
    ("image", re.compile(r"sanity-gravity:\{")),
    ("container", re.compile(r"\{\}-\{\}-1$")),
    ("env_var", re.compile(r"SANITY_IMAGE_")),
    ("volume", re.compile(r"^sg[_-]\{")),
    ("compose", re.compile(r"docker-compose\.\{")),
    ("ghcr", re.compile(r"ghcr\.io/")),
    ("layer", re.compile(r"^_base-\{|^_\{\}-\{")),
    ("backup", re.compile(r"sanity-migrate/")),
)

# Module-level prefix constants outside naming.py; see
# test_prefix_constants_only_in_naming.
_PREFIX_NAMES = frozenset(_PREFIX_VALUES) | {"LAYER_PREFIX"}

# Frozen 2026-08 when the value-object flow landed. This dict may
# only SHRINK; entries are
# "path::qualname" -> (family, ...). All three survivors are documented
# residuals, not oversights:
# - snapshot.py::_container_name: TagError fallback keeping the legacy
#   container shape for a user-typed non-tag --variant, so the doomed
#   existence probe still echoes the input instead of a raw TagError.
# - snapshot.py::snapshot_resolve_container: the dry-run "<variant>"
#   placeholder, display-only and deliberately outside the grammar.
# - upgrade.py::_migrate_one: the rollback ref of a genuine legacy
#   (flat-service) container must keep the OLD non-tag name; only the
#   repo prefix is shared with Naming.
KNOWN_IDENTITY_FSTRINGS = {
    "sanity_gravity/hooks/snapshot.py::_container_name": ("container",),
    "sanity_gravity/hooks/snapshot.py::snapshot_resolve_container": ("container",),
    "sanity_gravity/verbs/upgrade.py::_migrate_one": ("backup",),
}

# split("-") outside domain/ is tag grammar smuggled into a call site.
# cli/registry.py's parse_tag / tag_tier are the two survivors: they ARE
# the registry-validating grammar shim, retired once their callers take
# the Tag from the parse directly. This set may only shrink.
KNOWN_DASH_SPLITS = frozenset({
    "sanity_gravity/cli/registry.py::parse_tag",
    "sanity_gravity/cli/registry.py::tag_tier",
})


def _fv_text(expr: ast.expr) -> str:
    """Shape text for one interpolation: prefix constants are seen
    through (their literal value), everything else collapses to {}."""
    if isinstance(expr, ast.Attribute) and expr.attr in _PREFIX_VALUES:
        return _PREFIX_VALUES[expr.attr]
    if isinstance(expr, ast.Name) and expr.id in _PREFIX_VALUES:
        return _PREFIX_VALUES[expr.id]
    return "{}"


def _shape(node: ast.JoinedStr) -> str:
    parts = []
    for v in node.values:
        if isinstance(v, ast.Constant):
            parts.append(str(v.value))
        elif isinstance(v, ast.FormattedValue):
            parts.append(_fv_text(v.value))
        else:
            parts.append("{}")
    return "".join(parts)


class _Visitor(ast.NodeVisitor):
    """Collect per-qualname identity f-strings and split("-") calls."""

    def __init__(self) -> None:
        self.stack: list[str] = []
        self.fstring_families: dict[str, set[str]] = {}
        self.dash_splits: set[str] = set()

    @property
    def qualname(self) -> str:
        return ".".join(self.stack) if self.stack else "<module>"

    def _visit_scope(self, node) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = _visit_scope
    visit_AsyncFunctionDef = _visit_scope
    visit_ClassDef = _visit_scope

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        shape = _shape(node)
        for family, pattern in _FAMILIES:
            if pattern.search(shape):
                self.fstring_families.setdefault(self.qualname, set()).add(family)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in ("split", "rsplit")
            and len(node.args) >= 1
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "-"
        ):
            self.dash_splits.add(self.qualname)
        self.generic_visit(node)


def _scan():
    """Scan the production tree once; both guards read the result."""
    fstrings: dict[str, tuple[str, ...]] = {}
    splits: set[str] = set()
    for path in sorted(_PKG_ROOT.rglob("*.py")):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        visitor = _Visitor()
        visitor.visit(ast.parse(path.read_text(), filename=rel))
        if rel not in _ALLOWED:
            for qualname, families in visitor.fstring_families.items():
                fstrings[f"{rel}::{qualname}"] = tuple(sorted(families))
        if not rel.startswith("sanity_gravity/domain/"):
            splits.update(f"{rel}::{q}" for q in visitor.dash_splits)
    return fstrings, splits


def test_no_new_identity_fstrings():
    found, _ = _scan()
    new = {
        key: families
        for key, families in found.items()
        if not set(families) <= set(KNOWN_IDENTITY_FSTRINGS.get(key, ()))
    }
    assert not new, (
        f"identity f-strings outside domain/naming.py: {new}. Render this "
        "name via the matching Naming method instead - adding a ratchet "
        "entry is a design change, not a convenience."
    )


def test_identity_fstring_ratchet_only_shrinks():
    found, _ = _scan()
    stale = {
        key: tuple(sorted(set(families) - set(found.get(key, ()))))
        for key, families in KNOWN_IDENTITY_FSTRINGS.items()
        if not set(families) <= set(found.get(key, ()))
    }
    assert not stale, (
        f"ratchet entries no longer present - delete them so the debt "
        f"list keeps shrinking: {stale}"
    )


def test_prefix_constants_only_in_naming():
    offenders = []
    for path in sorted(_PKG_ROOT.rglob("*.py")):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel in _ALLOWED:
            continue
        for node in ast.walk(ast.parse(path.read_text(), filename=rel)):
            if isinstance(node, ast.Assign):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names = [node.target.id]
            else:
                continue
            for name in names:
                if name in _PREFIX_NAMES:
                    offenders.append(f"{rel}:{node.lineno}: {name}")
    assert not offenders, (
        "identity prefix constants may only be declared in "
        f"domain/naming.py (a constant is an f-string with extra steps): "
        f"{offenders}"
    )


def test_no_dash_splits_outside_domain():
    _, found = _scan()
    new = found - KNOWN_DASH_SPLITS
    assert not new, (
        f"split('-') outside domain/ smuggles the tag grammar into a call "
        f"site - parse once with Tag.parse and read the field: {sorted(new)}"
    )
    stale = KNOWN_DASH_SPLITS - found
    assert not stale, (
        f"dash-split ratchet entries no longer present - delete them: "
        f"{sorted(stale)}"
    )
