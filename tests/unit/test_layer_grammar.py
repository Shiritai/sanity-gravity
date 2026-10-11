"""LayerRef structure and the layer-name grammar.

A layer is structure; its name is a rendering. Naming.layer and
Naming.parse_layer are the only render/parse pair, bound here by a
round-trip property. LayerRef.parent is the single parent rule that
replaces the three hand-written chain builders in hooks/build.
"""
from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sanity_gravity.domain.layers import LayerError, LayerKind, LayerRef
from sanity_gravity.domain.naming import Naming
from sanity_gravity.domain.tags import RESERVED_SLUGS, Tag

slugs = st.from_regex(r"\A[a-z][a-z0-9]{0,7}\Z").filter(
    lambda s: s not in RESERVED_SLUGS
)
tags = st.builds(Tag, agent=slugs, desktop=slugs, connector=slugs, base=slugs)

layer_refs = st.one_of(
    st.builds(LayerRef.of_base, slugs),
    st.builds(LayerRef.of_desktop, slugs, slugs),
    st.builds(LayerRef.of_agent, slugs, slugs, slugs),
    st.builds(LayerRef.of_tag, tags),
)


@pytest.mark.parametrize("ref,rendered", [
    (LayerRef.of_base("ubuntu"), "_ubuntu"),
    (LayerRef.of_desktop("ubuntu", "xfce"), "_ubuntu-xfce"),
    (LayerRef.of_agent("ubuntu", "xfce", "ag"), "_ubuntu-xfce-ag"),
    (LayerRef.of_tag(Tag.parse("ag-xfce-kasm")), "ag-xfce-kasm"),
    (LayerRef.of_base("debian"), "_debian"),
    (LayerRef.of_desktop("debian", "xfce"), "_debian-xfce"),
    (LayerRef.of_agent("debian", "xfce", "ag"), "_debian-xfce-ag"),
    (LayerRef.of_tag(Tag.parse("ag-xfce-kasm-debian")), "ag-xfce-kasm-debian"),
])
def test_explicit_renderings(ref, rendered):
    """Literal names, not derived ones: an intermediate is its build
    path, and the final layer is its tag."""
    assert Naming.layer(ref) == rendered


@pytest.mark.parametrize("tag,base", [("cc-none-ssh", "ubuntu"),
                                      ("cc-none-ssh-debian", "debian")])
def test_parent_chain_of_a_final_tag(tag, base):
    ref = LayerRef.of_tag(Tag.parse(tag))
    assert ref.parent == LayerRef.of_agent(base, "none", "cc")
    assert ref.parent.parent == LayerRef.of_desktop(base, "none")
    assert ref.parent.parent.parent == LayerRef.of_base(base)
    assert ref.parent.parent.parent.parent is None
    assert ref.ancestors == (
        LayerRef.of_base(base),
        LayerRef.of_desktop(base, "none"),
        LayerRef.of_agent(base, "none", "cc"),
    )


def test_a_ref_binds_a_prefix_of_the_build_order():
    with pytest.raises(LayerError):
        LayerRef("ubuntu", agent="cc")  # desktop skipped
    with pytest.raises(LayerError):
        LayerRef("ubuntu", "xfce", tag=Tag.parse("cc-xfce-ssh"))  # agent skipped
    with pytest.raises(LayerError):  # the tag disagrees with the slots
        LayerRef("debian", "xfce", "cc", Tag.parse("cc-xfce-ssh"))
    with pytest.raises(LayerError):  # binds nothing
        LayerRef.from_bound([])
    with pytest.raises(LayerError):  # binds nothing, directly
        LayerRef(None)
    with pytest.raises(LayerError):  # base skipped
        LayerRef(None, "xfce")


@pytest.mark.parametrize(
    "slots",
    [("a-b",), ("ubuntu", "x-y"), ("UBUNTU",), ("_",), ("ubuntu", "none", "base")],
)
def test_a_ref_binds_only_valid_slugs(slots):
    """A slug holding '-' would render to a name that parses as a
    different, deeper ref."""
    with pytest.raises(LayerError):
        LayerRef(*slots)


@pytest.mark.parametrize(
    "name",
    ["_", "_ubuntu-", "_-x", "_ubuntu--cc", "_ubuntu-xfce-cc-kasm",
     "_base", "_UBUNTU", "__"],
)
def test_malformed_layer_names_are_rejected(name):
    """A segment that is no valid slug, and a fully bound prefix, which
    is a final image and carries no '_': neither may decode to a ref."""
    with pytest.raises(LayerError):
        Naming.parse_layer(name)


@given(layer_refs)
def test_layer_render_parse_roundtrip(ref):
    """Also the injectivity guarantee: if two distinct refs rendered to
    the same name, parse could return only one of them, so this
    round-trip is red for exactly the collisions a separate
    distinct-names property would have caught."""
    assert Naming.parse_layer(Naming.layer(ref)) == ref


@given(layer_refs)
def test_parent_is_one_step_shallower(ref):
    """Depth arithmetic, not one worked example: ``sort_key`` orders
    plans by ``int(kind)`` alone, which is only sound if every parent
    edge drops exactly one level for *every* slug.

    test_parent_chain_of_a_final_tag walks all four kinds for one
    concrete tag and so covers the same edges, but it cannot see a
    parent rule that branches on slug content - e.g. returning None
    for desktop slugs longer than four characters leaves that test
    green (its slug is "none") and this one red.
    """
    parent = ref.parent
    assert (parent is None) is (ref.kind is LayerKind.BASE)
    if parent is not None:
        assert int(parent.kind) == int(ref.kind) - 1


@given(st.lists(layer_refs, min_size=1, max_size=10))
def test_sort_key_puts_parents_before_children(refs):
    """Each drawn ref brings its ancestors along: independently drawn
    refs almost never include one another's parents, which would leave
    the ordering assertion with nothing to compare."""
    pool = {a for r in refs for a in (*r.ancestors, r)}
    ordered = sorted(pool, key=lambda r: r.sort_key)
    index = {r: i for i, r in enumerate(ordered)}
    for r in ordered:
        if r.parent is not None:
            assert index[r.parent] < index[r]


@given(st.lists(layer_refs, min_size=1, max_size=10))
def test_sort_key_tells_every_ref_apart(refs):
    """The planner sorts a set; equal keys would leave the plan order to
    hash order, which varies between runs."""
    pool = set(refs)
    assert len({r.sort_key for r in pool}) == len(pool)
