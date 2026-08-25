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
tag_strings = tags.map(str)

#: Parse inputs weighted toward the parseable region and its near
#: misses: plain random text (the old strategy) almost never parses, so
#: the injectivity assertion below was effectively unreachable - a
#: silently canonicalizing parse (e.g. strip/lower) stayed green.
parse_inputs = st.one_of(
    tag_strings,
    tag_strings.map(lambda s: " " + s),
    tag_strings.map(lambda s: s + " "),
    tag_strings.map(str.upper),
    st.text(max_size=40),
)


def test_parse_render_roundtrip_explicit():
    tag = Tag.parse("ag-xfce-kasm")
    assert tag == Tag(agent="ag", desktop="xfce", connector="kasm")
    assert str(tag) == "ag-xfce-kasm"


@pytest.mark.parametrize(
    "bad,match",
    [
        ("ag-xfce", "Invalid tag format"),          # arity: 2 parts
        ("a-b-c-d", "Invalid tag format"),          # arity: 4 parts
        ("", "Invalid tag format"),                 # arity: 1 part

        ("AG-xfce-kasm", r"expected \[a-z\]"),      # charset, at construction
        ("a_g-xfce-kasm", r"expected \[a-z\]"),
        ("9g-xfce-kasm", r"expected \[a-z\]"),
        ("base-xfce-kasm", "reserved"),             # layer-grammar collision
    ],
)
def test_malformed_input_raises_a_named_tag_error(bad, match):
    """Arity is a parse question; alphabet and reservation are enforced
    by the constructor so every Tag in the process round-trips, however
    it was built ('base' would make '_base-<desktop>' ambiguous)."""
    with pytest.raises(TagError, match=match):
        Tag.parse(bad)


def test_reserved_slug_rejected_at_direct_construction():
    with pytest.raises(TagError, match="reserved"):
        Tag(agent="base", desktop="xfce", connector="kasm")


def test_parse_requires_no_parser_argument():
    """The injected-parser mechanism is gone: the type owns the grammar."""
    with pytest.raises(TypeError):
        Tag.parse("ag-xfce-kasm", parser=lambda s: s)  # type: ignore[call-arg]


@given(tags)
def test_render_parse_is_identity(tag):
    assert Tag.parse(str(tag)) == tag


@given(parse_inputs)
def test_parse_never_returns_a_non_roundtripping_value(s):
    """Injectivity contract: no input parses into a value whose
    canonical form differs from what was given."""
    try:
        tag = Tag.parse(s)
    except TagError:
        return
    assert str(tag) == s
