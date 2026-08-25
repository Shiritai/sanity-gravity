"""A tag is parsed once per boundary crossing, then flows as a value.

`Tag` has value semantics, so re-parsing the same string mid-flow is
harmless in the sense that it cannot produce a *different* tag. It is
still a defect: it means the flow is carrying the user's string rather
than the parsed value, so every consumer downstream must re-validate,
re-derive, and re-decide what a malformed input means. The bug that
pattern produces is not a wrong Tag - it is two call sites disagreeing
about whether a string was already checked.

So construction is confined to boundaries, where a string genuinely
becomes a value for the first time:

- argv, via ``core.registry.resolve_tag``
- the plugin manifest tree, via ``PluginRegistry.valid_tags``
- a docker label read back off a container, via
  ``verbs.lifecycle.find_project_containers``
- legacy flat service names, via ``verbs.lifecycle.legacy_target_tag``
- a layer name, via ``Naming.parse_layer`` (the declared inverse of
  ``Naming.layer``; a property test binds the pair)

Everywhere else the value is threaded through. This ledger may only
shrink: a new entry means a flow went back to carrying a string.
"""

from __future__ import annotations

import ast
from collections import Counter

import pytest

from tests.support import (
    PKG_ROOT,
    QualnameVisitor,
    node_name,
    parse,
    py_files,
    source_tree_guard,
    uncovered,
)

# mutmut rewrites each function into x_<name>__mutmut_N in its generated
# tree, so a guard keyed on qualname sees dozens of phantom sites there.
# Like the other source-shape guards, this one only speaks about the real
# source tree.
pytestmark = source_tree_guard

#: Frozen 2026-08 when tag values were threaded through the flow
#: contexts. ``path::qualname`` -> number of construction sites.
#: Each entry is a boundary where a string first becomes a Tag.
KNOWN_TAG_CONSTRUCTION: dict[str, int] = {
    # argv: the one place a user-typed tag is validated.
    "sanity_gravity/core/registry.py::resolve_tag": 1,
    # The plugin tree: slugs come from manifests, so the matrix is built
    # from parts rather than parsed from a string.
    "sanity_gravity/plugins/registry.py::PluginRegistry.valid_tags": 1,
    # Docker label read-back: the service label is the canonical tag, and
    # this is the only place it is turned into a value.
    "sanity_gravity/verbs/lifecycle.py::find_project_containers": 1,
    # Legacy flat service names map onto modern tags. Two shapes cross
    # here: a service that already IS a tag, and a flat core/kasm/vnc
    # name rebuilt as ag-xfce-<connector>.
    "sanity_gravity/verbs/lifecycle.py::legacy_target_tag": 2,
    # The declared inverse of Naming.layer; a property test binds them.
    "sanity_gravity/domain/naming.py::Naming.parse_layer": 1,
    # pull's argv boundary. --variant all expands to the registry's
    # already-parsed matrix, so only user-typed variants are parsed.
    "sanity_gravity/verbs/pull.py::_as_tag": 1,
    # A user-typed --variant that may legitimately not be a tag: the
    # TagError branch keeps the legacy not-found message instead of
    # replacing a graceful bail-out with a traceback.
    "sanity_gravity/hooks/snapshot.py::_container_name": 1,
}


class _TagConstructionVisitor(QualnameVisitor):
    """Collect ``Tag(...)`` and ``Tag.parse(...)`` sites by qualname."""

    def __init__(self) -> None:
        super().__init__()
        self.sites: Counter[str] = Counter()

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        constructed = (
            isinstance(func, ast.Name) and func.id == "Tag"
        ) or (
            isinstance(func, ast.Attribute)
            and func.attr == "parse"
            and node_name(func.value) == "Tag"
        )
        if constructed:
            self.sites[self.qualname] += 1
        self.generic_visit(node)


def _scan() -> Counter[str]:
    found: Counter[str] = Counter()
    for path, rel in py_files(PKG_ROOT):
        visitor = _TagConstructionVisitor()
        visitor.visit(parse(path))
        for qualname, n in visitor.sites.items():
            found[f"{rel}::{qualname}"] += n
    return found


def test_tag_is_constructed_only_at_boundaries():
    """A construction site outside the ledger means a flow re-parsed a
    string it was already handed as a value."""
    found = _scan()
    new = {k: n for k, n in found.items() if k not in KNOWN_TAG_CONSTRUCTION}
    grown = {
        k: (KNOWN_TAG_CONSTRUCTION[k], n)
        for k, n in found.items()
        if k in KNOWN_TAG_CONSTRUCTION and n > KNOWN_TAG_CONSTRUCTION[k]
    }
    assert not new, (
        "Tag constructed outside a boundary - thread the parsed value "
        f"through instead of re-parsing the string: {sorted(new)}"
    )
    assert not grown, (
        "a boundary gained extra Tag constructions; parse once and reuse "
        f"the value: {grown}"
    )


def test_tag_construction_ledger_only_shrinks():
    """Debt paid but not deleted leaves the slot open to regrow."""
    stale = uncovered(KNOWN_TAG_CONSTRUCTION, _scan())
    assert not stale, (
        "these boundaries no longer construct as many Tags as frozen; "
        f"shrink KNOWN_TAG_CONSTRUCTION to match: {stale}"
    )


@pytest.mark.parametrize(
    "src,expected",
    [
        ("from x import Tag\ndef f():\n    return Tag.parse('a-b-c')\n", 1),
        ("from x import Tag\ndef f():\n    return Tag(agent='a', desktop='b', connector='c')\n", 1),
        ("def f():\n    return NotATag.parse('a-b-c')\n", 0),
        ("def f():\n    return parse('a-b-c')\n", 0),
        ("class C:\n    def m(self):\n        return Tag.parse('a-b-c')\n", 1),
    ],
    ids=["Tag.parse", "Tag(...)", "other.parse", "bare parse", "inside a method"],
)
def test_visitor_sees_construction_and_only_construction(src, expected):
    """Guard the guard: a detector that misses ``Tag(...)`` would let the
    matrix be rebuilt by hand, and one that fires on any ``.parse`` would
    make the ledger meaningless."""
    visitor = _TagConstructionVisitor()
    visitor.visit(ast.parse(src))
    assert sum(visitor.sites.values()) == expected
