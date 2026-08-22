"""Tag owns its grammar: parse and render are mutually inverse.

The grammar lives in exactly one type. Constraint validation (does this
agent exist, is the combination satisfiable) is a different question and
stays in core.registry; nothing here touches a registry.
"""
from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sanity_gravity.domain.tags import RESERVED_SLUGS, Tag, TagError

slugs = st.from_regex(r"\A[a-z][a-z0-9]{0,7}\Z").filter(
    lambda s: s not in RESERVED_SLUGS
)
tags = st.builds(Tag, agent=slugs, desktop=slugs, connector=slugs)


def test_parse_render_roundtrip_explicit():
    tag = Tag.parse("ag-xfce-kasm")
    assert tag == Tag(agent="ag", desktop="xfce", connector="kasm")
    assert str(tag) == "ag-xfce-kasm"


@pytest.mark.parametrize("bad", ["ag-xfce", "a-b-c-d", "", "ag"])
def test_wrong_arity_raises_tag_error_naming_the_input(bad):
    with pytest.raises(TagError, match="Invalid tag format"):
        Tag.parse(bad)


@pytest.mark.parametrize("bad", ["AG-xfce-kasm", "a_g-xfce-kasm", "9g-xfce-kasm"])
def test_slug_outside_charset_rejected_at_construction(bad):
    """Every Tag in the process round-trips, however it was built:
    the alphabet is enforced by the constructor, not by the parser."""
    with pytest.raises(TagError, match="slug"):
        Tag.parse(bad)


def test_reserved_slug_base_rejected():
    """An agent slug 'base' makes the layer name '_base-<desktop>'
    collide with the desktop layer's rendering - the layer grammar stops
    being injective. Reserved across all dimensions for simplicity."""
    with pytest.raises(TagError, match="reserved"):
        Tag(agent="base", desktop="xfce", connector="kasm")


def test_parse_requires_no_parser_argument():
    """The injected-parser mechanism is gone: the type owns the grammar."""
    with pytest.raises(TypeError):
        Tag.parse("ag-xfce-kasm", parser=lambda s: s)  # type: ignore[call-arg]


@given(tags)
def test_render_parse_is_identity(tag):
    assert Tag.parse(str(tag)) == tag


@given(st.text(max_size=40))
def test_parse_never_returns_a_non_roundtripping_value(s):
    """Injectivity contract: no input parses into a value whose
    canonical form differs from what was given."""
    try:
        tag = Tag.parse(s)
    except TagError:
        return
    assert str(tag) == s
