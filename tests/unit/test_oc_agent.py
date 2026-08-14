"""Unit tests for the ``oc`` (OpenCode CLI) agent plugin.

The agent slug is the 2-char ``oc``; the installed binary is
``opencode``. These tests exercise only the plugin's manifest and its
interaction with the manifest-driven kernel (registry discovery,
capability solver, tier enumeration). No Docker is involved -- the
container-side install is covered by
``tests/integration/test_oc_agent.py``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from sanity_gravity.domain.capability import (  # noqa: E402
    CapabilityConflictError,
    solve,
)
from sanity_gravity.domain.tags import Tag  # noqa: E402
from sanity_gravity.plugins.registry import (  # noqa: E402
    PluginRegistry,
    default_registry,
    reset_default_registry,
)


PLUGINS_DIR = _REPO_ROOT / "plugins"

# The four combinations a pure-CLI agent (no GUI requirement) yields:
# every desktop/connector pair that itself satisfies the display rule.
OC_VALID_TAGS = [
    Tag("oc", "xfce", "kasm"),
    Tag("oc", "xfce", "ssh"),
    Tag("oc", "xfce", "vnc"),
    Tag("oc", "none", "ssh"),
]


@pytest.fixture(scope="module")
def reg() -> PluginRegistry:
    """Cold-load the builtin registry from the on-disk plugin tree."""
    reset_default_registry()
    return default_registry(PLUGINS_DIR)


# -- discovery ----------------------------------------------------------


def test_oc_is_discovered(reg):
    """The registry walks ``plugins/agents/oc/`` with no code changes."""
    assert "oc" in reg.agents


def test_oc_manifest_identity(reg):
    m = reg.agents["oc"]
    assert m.slug == "oc"
    assert m.name == "opencode-cli"
    assert m.kind == "agent"
    assert m.api_version == "1"


def test_oc_is_pure_cli_agent(reg):
    """oc needs no GUI: it provides and requires nothing."""
    m = reg.agents["oc"]
    assert m.provides == ()
    assert m.requires == ()


def test_oc_injects_no_host_env(reg):
    """The sandbox must not auto-leak host secrets: oc declares no env,
    same as the other CLI agents. Auth is via in-container
    `opencode auth login`."""
    assert reg.agents["oc"].environment == ()


# -- tier ---------------------------------------------------------------


def test_oc_is_official(reg):
    """oc declares no tier, so it defaults to official and enters the CI
    build/verify and publish matrix."""
    assert reg.agents["oc"].tier == "official"


def test_oc_tags_enter_the_official_matrix():
    """All four oc-* tags must reach OFFICIAL_TAGS (the `list --json`
    source CI enumerates its matrices from)."""
    from sanity_gravity.cli.registry import OFFICIAL_TAGS, tag_tier

    oc_tags = [t for t in OFFICIAL_TAGS if t.startswith("oc-")]
    assert sorted(oc_tags) == [
        "oc-cinnamon-kasm", "oc-cinnamon-ssh", "oc-cinnamon-vnc",
        "oc-none-ssh", "oc-xfce-kasm", "oc-xfce-ssh", "oc-xfce-vnc",
    ]
    for t in oc_tags:
        assert tag_tier(t) == "official"


# -- capability solving -------------------------------------------------


@pytest.mark.parametrize("tag", OC_VALID_TAGS, ids=lambda t: str(t))
def test_oc_valid_tags_pass(tag, reg):
    assert solve(tag, reg) == tag


def test_oc_appears_in_valid_tags(reg):
    assert set(OC_VALID_TAGS).issubset(set(reg.valid_tags()))


def test_oc_none_kasm_fails(reg):
    """A GUI connector still needs a display, even for a headless agent."""
    with pytest.raises(CapabilityConflictError) as excinfo:
        solve(Tag("oc", "none", "kasm"), reg)
    assert excinfo.value.missing == frozenset({"display"})


def test_oc_none_vnc_fails(reg):
    with pytest.raises(CapabilityConflictError):
        solve(Tag("oc", "none", "vnc"), reg)
