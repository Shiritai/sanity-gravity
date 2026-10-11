"""Tag owns its grammar: render is canonical and parse inverts it.

The grammar lives in exactly one type. Constraint validation (does this
agent exist, is the combination satisfiable) is a different question and
stays in core.registry; nothing here touches a registry.
"""
from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sanity_gravity.domain.tags import (
    DEFAULT_BASE,
    RESERVED_SLUGS,
    SEP,
    Tag,
    TagError,
)

slugs = st.from_regex(r"\A[a-z][a-z0-9]{0,7}\Z").filter(
    lambda s: s not in RESERVED_SLUGS
)
#: The default base is drawn often on purpose: it is the one value whose
#: rendering differs from its spelling.
bases = st.one_of(st.just(DEFAULT_BASE), slugs)
tags = st.builds(Tag, agent=slugs, desktop=slugs, connector=slugs, base=bases)
tag_strings = st.one_of(
    tags.map(str),
    st.builds(SEP.join, st.tuples(slugs, slugs, slugs, bases)),
)

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


def test_the_base_segment_is_last_and_the_default_is_elided():
    assert Tag.parse("cc-none-ssh").base == DEFAULT_BASE
    assert Tag.parse("cc-none-ssh") == Tag.parse(f"cc-none-ssh-{DEFAULT_BASE}")
    assert str(Tag.parse(f"cc-none-ssh-{DEFAULT_BASE}")) == "cc-none-ssh"
    other = Tag.parse("cc-none-ssh-debian")
    assert (other.agent, other.base) == ("cc", "debian")
    assert str(other) == "cc-none-ssh-debian"


@pytest.mark.parametrize(
    "bad,match",
    [
        ("ag-xfce", "Invalid tag format"),          # arity: 2 parts
        ("a-b-c-d-e", "Invalid tag format"),        # arity: 5 parts
        ("", "Invalid tag format"),                 # arity: 1 part
        ("cc-none-ssh-", r"expected \[a-z\]"),      # empty base segment

        ("AG-xfce-kasm", r"expected \[a-z\]"),      # charset, at construction
        ("a_g-xfce-kasm", r"expected \[a-z\]"),
        ("9g-xfce-kasm", r"expected \[a-z\]"),
        ("cc-none-ssh\n", r"expected \[a-z\]"),     # '$' would accept it
        # '.' is reserved for an in-segment version qualifier.
        ("cc.1-none-ssh", r"expected \[a-z\]"),
        ("base-xfce-kasm", "reserved"),             # layer-grammar collision
        ("cc-none-ssh-base", "reserved"),
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
def test_parse_canonicalises_nothing_but_the_default_base(s):
    """Eliding a spelled-out default base is the only rewrite parse
    performs: any other difference between an input and the canonical
    form of what it parsed to (a stripped space, a lowered letter) means
    two spellings of one identity slipped past the grammar."""
    try:
        tag = Tag.parse(s)
    except TagError:
        return
    four_segments = s.count(SEP) == 3
    expected = s.removesuffix(SEP + DEFAULT_BASE) if four_segments else s
    assert str(tag) == expected
