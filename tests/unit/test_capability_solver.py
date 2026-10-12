"""Tests for ``lib/capability.py``: provides/requires set solver."""
from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sanity_gravity.domain.capability import (
    CapabilityConflictError,
    _satisfied,
    solve,
)
from sanity_gravity.domain.tags import Tag
from sanity_gravity.plugins.registry import (
    PluginRegistry,
    default_registry,
    reset_default_registry,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def reg() -> PluginRegistry:
    """Cold-load the builtin registry. Module-scoped to keep the fixture
    cheap; the solver is pure so order of tests doesn't matter."""
    reset_default_registry()
    return default_registry(_REPO_ROOT / "plugins")


# 11 known-good tags carried over from PR #5's VALID_TAGS.
KNOWN_GOOD_TAGS: list[Tag] = [
    Tag("ag", "xfce", "kasm"),
    Tag("ag", "xfce", "ssh"),
    Tag("ag", "xfce", "vnc"),
    Tag("gc", "xfce", "kasm"),
    Tag("gc", "xfce", "ssh"),
    Tag("gc", "xfce", "vnc"),
    Tag("gc", "none", "ssh"),
    Tag("cc", "xfce", "kasm"),
    Tag("cc", "xfce", "ssh"),
    Tag("cc", "xfce", "vnc"),
    Tag("cc", "none", "ssh"),
]


@pytest.mark.parametrize("tag", KNOWN_GOOD_TAGS, ids=lambda t: str(t))
def test_known_good_tags_pass(tag, reg):
    """Each of the 11 legacy-valid tags must satisfy provides ⊇ requires."""
    assert solve(tag, reg) == tag


def test_ag_none_ssh_fails(reg):
    """``ag`` requires display; ``none`` provides nothing → conflict."""
    with pytest.raises(CapabilityConflictError) as excinfo:
        solve(Tag("ag", "none", "ssh"), reg)
    assert "display" in excinfo.value.missing
    assert "missing required capabilities" in str(excinfo.value)


def test_gc_none_kasm_fails(reg):
    """``kasm`` requires display; headless ``none`` doesn't provide it."""
    with pytest.raises(CapabilityConflictError) as excinfo:
        solve(Tag("gc", "none", "kasm"), reg)
    assert excinfo.value.missing == frozenset({"display"})


def test_gc_none_vnc_fails(reg):
    with pytest.raises(CapabilityConflictError):
        solve(Tag("gc", "none", "vnc"), reg)


def test_solver_is_pure(reg):
    """Solver does not mutate plugins or registry."""
    a_before = reg.agents["ag"].requires
    solve(Tag("ag", "xfce", "kasm"), reg)
    assert reg.agents["ag"].requires == a_before


def test_unknown_slug_raises_keyerror(reg):
    """Unknown slugs are *not* capability conflicts; surface as KeyError."""
    with pytest.raises(KeyError):
        solve(Tag("nope", "xfce", "ssh"), reg)


# ---------------------------------------------------------------------------
# Requirement alternatives: ``a|b`` is met by any one of them.
# ---------------------------------------------------------------------------

caps = st.from_regex(r"\A[a-z][a-z0-9:]{0,6}\Z")
provided_sets = st.frozensets(caps, max_size=5)


@given(caps, provided_sets)
def test_a_requirement_without_alternatives_is_plain_membership(req, provided):
    """A requirement that lists no alternatives is plain membership."""
    assert _satisfied(req, provided) is (req in provided)


@given(st.lists(caps, min_size=1, max_size=4), caps, provided_sets)
def test_an_extra_alternative_never_breaks_a_met_requirement(alts, extra, provided):
    req = "|".join(alts)
    if _satisfied(req, provided):
        assert _satisfied(f"{req}|{extra}", provided)


class _Manifest:
    def __init__(self, provides=(), requires=()):
        self.provides, self.requires = tuple(provides), tuple(requires)


class _Registry:
    """Just enough registry for solve: every slug of a kind not listed
    resolves to a plugin that provides and requires nothing."""

    def __init__(self, **by_kind):
        self.by_kind = by_kind

    def get(self, kind, slug):
        return self.by_kind.get(kind, _Manifest())


_DISTRO_REQ = "ubuntu:noble|debian:bookworm"


@pytest.mark.parametrize("distro", ["ubuntu:noble", "debian:bookworm"])
def test_any_one_alternative_satisfies_a_requirement(distro):
    reg = _Registry(desktop=_Manifest(provides=[distro]),
                    connector=_Manifest(requires=[_DISTRO_REQ]))
    tag = Tag("aa", "dd", "cc")
    assert solve(tag, reg) == tag


def test_an_unmet_requirement_is_reported_as_written():
    reg = _Registry(desktop=_Manifest(provides=["alpine:edge"]),
                    connector=_Manifest(requires=[_DISTRO_REQ]))
    with pytest.raises(CapabilityConflictError) as excinfo:
        solve(Tag("aa", "dd", "cc"), reg)
    assert excinfo.value.missing == frozenset({_DISTRO_REQ})
