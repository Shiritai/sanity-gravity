"""Tests for ``lib/capability.py``: provides/requires set solver."""
from __future__ import annotations

from pathlib import Path

import pytest


from sanity_gravity.domain.capability import CapabilityConflictError, solve
from sanity_gravity.domain.tags import Tag
from sanity_gravity.plugins.registry import (
    PluginRegistry, default_registry, reset_default_registry,
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
