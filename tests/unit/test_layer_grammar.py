"""LayerRef structure and the layer-name grammar.

A layer is structure; its name is a rendering. Naming.layer and
Naming.parse_layer are the only render/parse pair, bound here by a
round-trip property. LayerRef.parent is the single parent rule that
replaces the three hand-written chain builders in hooks/build.
"""
from __future__ import annotations

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from sanity_gravity.domain.layers import LayerError, LayerKind, LayerRef
from sanity_gravity.domain.naming import Naming
from sanity_gravity.domain.tags import RESERVED_SLUGS, Tag

slugs = st.from_regex(r"\A[a-z][a-z0-9]{0,7}\Z").filter(
    lambda s: s not in RESERVED_SLUGS
)
tags = st.builds(Tag, agent=slugs, desktop=slugs, connector=slugs)

layer_refs = st.one_of(
    st.just(LayerRef.base()),
    st.builds(LayerRef.of_desktop, slugs),
    st.builds(LayerRef.of_agent, slugs, slugs),
    st.builds(LayerRef.of_tag, tags),
)


def test_explicit_renderings():
    assert Naming.layer(LayerKind.BASE) == "_base"
    assert Naming.layer(LayerKind.DESKTOP, "xfce") == "_base-xfce"
    assert Naming.layer(LayerKind.AGENT, "ag-xfce") == "_ag-xfce"
    assert Naming.layer(LayerKind.CONNECTOR, "ag-xfce-kasm") == "ag-xfce-kasm"


def test_parent_chain_of_a_final_tag():
    ref = LayerRef.of_tag(Tag.parse("cc-none-ssh"))
    assert ref.parent == LayerRef.of_agent("cc", "none")
    assert ref.parent.parent == LayerRef.of_desktop("none")
    assert ref.parent.parent.parent == LayerRef.base()
    assert ref.parent.parent.parent.parent is None
    assert ref.ancestors == (
        LayerRef.base(),
        LayerRef.of_desktop("none"),
        LayerRef.of_agent("cc", "none"),
    )


def test_field_occupancy_enforced():
    with pytest.raises(LayerError):
        LayerRef(LayerKind.BASE, desktop="xfce")
    with pytest.raises(LayerError):
        LayerRef(LayerKind.AGENT, agent="ag")  # desktop missing


def test_layer_kind_parse_rejects_unknown():
    assert LayerKind.parse("desktop") is LayerKind.DESKTOP
    with pytest.raises(LayerError, match="base, desktop, agent, connector"):
        LayerKind.parse("weapon")


def test_selector_arity_mismatch_is_a_readable_error():
    with pytest.raises(LayerError, match="--layer"):
        LayerRef.of(LayerKind.AGENT, "ag")          # needs agent-desktop
    with pytest.raises(LayerError, match="--layer"):
        LayerRef.of(LayerKind.AGENT, "ag-xfce-kasm")


@given(layer_refs)
def test_layer_render_parse_roundtrip(ref):
    assert Naming.parse_layer(Naming.layer(ref.kind, ref.detail)) == ref


@given(layer_refs, layer_refs)
def test_distinct_layers_render_to_distinct_names(a, b):
    assume(a != b)
    assert Naming.layer(a.kind, a.detail) != Naming.layer(b.kind, b.detail)


@given(layer_refs)
def test_selector_roundtrip(ref):
    """(--layer, --layer-target) is exactly the (kind, detail) pair."""
    assert LayerRef.of(ref.kind, ref.detail) == ref


@given(layer_refs)
def test_parent_is_one_step_shallower(ref):
    parent = ref.parent
    assert (parent is None) is (ref.kind is LayerKind.BASE)
    if parent is not None:
        assert int(parent.kind) == int(ref.kind) - 1


@given(st.lists(layer_refs, min_size=1, max_size=10))
def test_sort_key_puts_parents_before_children(refs):
    ordered = sorted(set(refs), key=lambda r: r.sort_key)
    index = {r: i for i, r in enumerate(ordered)}
    for r in ordered:
        if r.parent is not None and r.parent in index:
            assert index[r.parent] < index[r]
