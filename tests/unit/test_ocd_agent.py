"""Unit tests for the ``ocd`` (OpenCode Desktop) agent plugin.

The agent slug is the 3-char ``ocd``; the installed app is the OpenCode
Desktop Electron build under ``/opt/OpenCode``. Unlike the ``oc`` CLI
plugin, ``ocd`` is a GUI agent: it declares ``requires = ["display"]``, so
only GUI desktops (``xfce``) form valid tags. These tests
exercise only the plugin's manifest and its interaction with the
manifest-driven kernel (registry discovery, capability solver, tier
enumeration). No Docker is involved -- the container-side install is a
plain apt/curl step guarded by the pinned version + SHA256 checksums in
the Dockerfile.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from sanity_gravity.domain.capability import (
    CapabilityConflictError,
    solve,
)
from sanity_gravity.domain.tags import Tag
from sanity_gravity.plugins.registry import (
    PluginRegistry,
    default_registry,
    reset_default_registry,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

PLUGINS_DIR = _REPO_ROOT / "plugins"

# A GUI agent pairs with every GUI desktop/connector combination that
# itself satisfies the display rule: xfce x {kasm, ssh, vnc}.
OCD_VALID_TAGS = [
    Tag("ocd", "xfce", "kasm"),
    Tag("ocd", "xfce", "ssh"),
    Tag("ocd", "xfce", "vnc"),
]


@pytest.fixture(scope="module")
def reg() -> PluginRegistry:
    """Cold-load the builtin registry from the on-disk plugin tree."""
    reset_default_registry()
    return default_registry(PLUGINS_DIR)


# -- discovery ----------------------------------------------------------


def test_ocd_is_discovered(reg):
    """The registry walks ``plugins/agents/ocd/`` with no code changes."""
    assert "ocd" in reg.agents


def test_ocd_manifest_identity(reg):
    m = reg.agents["ocd"]
    assert m.slug == "ocd"
    assert m.name == "opencode-desktop"
    assert m.kind == "agent"
    assert m.api_version == "1"


def test_ocd_requires_display(reg):
    """ocd is a GUI app: it needs a display, unlike the oc CLI plugin."""
    m = reg.agents["ocd"]
    assert m.provides == ()
    assert m.requires == ("display",)


def test_ocd_injects_no_host_env(reg):
    """The sandbox must not auto-leak host secrets: ocd declares no env,
    same as the other agents. Auth is via in-app `opencode auth login`."""
    assert reg.agents["ocd"].environment == ()


# -- tier ---------------------------------------------------------------


def test_ocd_is_community(reg):
    """ocd ships at community tier, so it is buildable and runnable
    locally but stays out of the CI and publish matrix."""
    assert reg.agents["ocd"].tier == "community"


def test_ocd_tags_stay_out_of_the_official_matrix():
    """The six ocd tags reach VALID_TAGS but not OFFICIAL_TAGS (the
    `list --json` source CI enumerates its matrices from)."""
    from sanity_gravity.core.registry import (
        OFFICIAL_TAGS,
        VALID_TAGS,
        resolve_tag,
        tag_tier,
    )

    assert [t for t in OFFICIAL_TAGS if resolve_tag(t).agent == "ocd"] == []
    ocd_tags = [t for t in VALID_TAGS if resolve_tag(t).agent == "ocd"]
    assert sorted(ocd_tags) == [
        "ocd-lxqt-kasm", "ocd-lxqt-ssh", "ocd-lxqt-vnc",
        "ocd-xfce-kasm", "ocd-xfce-ssh", "ocd-xfce-vnc",
    ]
    for t in ocd_tags:
        assert tag_tier(resolve_tag(t)) == "community"


# -- capability solving -------------------------------------------------


@pytest.mark.parametrize("tag", OCD_VALID_TAGS, ids=lambda t: str(t))
def test_ocd_valid_tags_pass(tag, reg):
    assert solve(tag, reg) == tag


def test_ocd_appears_in_valid_tags(reg):
    assert set(OCD_VALID_TAGS).issubset(set(reg.valid_tags()))


@pytest.mark.parametrize(
    "tag", [Tag("ocd", "none", "kasm"), Tag("ocd", "none", "vnc"), Tag("ocd", "none", "ssh")]
)
def test_ocd_headless_tags_fail(tag, reg):
    """The desktop app cannot run headless: every none-* combo fails on
    the missing display, not just the GUI connectors."""
    with pytest.raises(CapabilityConflictError) as excinfo:
        solve(tag, reg)
    assert excinfo.value.missing == frozenset({"display"})
