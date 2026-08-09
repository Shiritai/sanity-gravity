"""Unit tests for the ``od`` (OpenCode Desktop) agent plugin.

The agent slug is the 2-char ``od``; the installed app is the OpenCode
Desktop Electron build under ``/opt/OpenCode``. Unlike the ``oc`` CLI
plugin, ``od`` is a GUI agent: it declares ``requires = ["display"]``, so
only GUI desktops (``xfce``) form valid tags. These tests
exercise only the plugin's manifest and its interaction with the
manifest-driven kernel (registry discovery, capability solver, tier
enumeration). No Docker is involved -- the container-side install is a
plain apt/curl step guarded by the pinned version + SHA256 checksums in
the Dockerfile.
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

# A GUI agent pairs with every GUI desktop/connector combination that
# itself satisfies the display rule: xfce x {kasm, ssh, vnc}.
OD_VALID_TAGS = [
    Tag("od", "xfce", "kasm"),
    Tag("od", "xfce", "ssh"),
    Tag("od", "xfce", "vnc"),
]


@pytest.fixture(scope="module")
def reg() -> PluginRegistry:
    """Cold-load the builtin registry from the on-disk plugin tree."""
    reset_default_registry()
    return default_registry(PLUGINS_DIR)


# -- discovery ----------------------------------------------------------


def test_od_is_discovered(reg):
    """The registry walks ``plugins/agents/od/`` with no code changes."""
    assert "od" in reg.agents


def test_od_manifest_identity(reg):
    m = reg.agents["od"]
    assert m.slug == "od"
    assert m.name == "opencode-desktop"
    assert m.kind == "agent"
    assert m.api_version == "1"


def test_od_requires_display(reg):
    """od is a GUI app: it needs a display, unlike the oc CLI plugin."""
    m = reg.agents["od"]
    assert m.provides == ()
    assert m.requires == ("display",)


def test_od_injects_no_host_env(reg):
    """The sandbox must not auto-leak host secrets: od declares no env,
    same as the other agents. Auth is via in-app `opencode auth login`."""
    assert reg.agents["od"].environment == ()


# -- tier ---------------------------------------------------------------


def test_od_is_official(reg):
    """od declares no tier, so it defaults to official and enters the CI
    build/verify and publish matrix."""
    assert reg.agents["od"].tier == "official"


def test_od_tags_enter_the_official_matrix():
    """All three od-* tags must reach OFFICIAL_TAGS (the `list --json`
    source CI enumerates its matrices from)."""
    from sanity_gravity.cli.registry import OFFICIAL_TAGS, tag_tier

    od_tags = [t for t in OFFICIAL_TAGS if t.startswith("od-")]
    assert sorted(od_tags) == [
        "od-xfce-kasm", "od-xfce-ssh", "od-xfce-vnc",
    ]
    for t in od_tags:
        assert tag_tier(t) == "official"


# -- capability solving -------------------------------------------------


@pytest.mark.parametrize("tag", OD_VALID_TAGS, ids=lambda t: str(t))
def test_od_valid_tags_pass(tag, reg):
    assert solve(tag, reg) == tag


def test_od_appears_in_valid_tags(reg):
    assert set(OD_VALID_TAGS).issubset(set(reg.valid_tags()))


@pytest.mark.parametrize(
    "tag", [Tag("od", "none", "kasm"), Tag("od", "none", "vnc"), Tag("od", "none", "ssh")]
)
def test_od_headless_tags_fail(tag, reg):
    """The desktop app cannot run headless: every none-* combo fails on
    the missing display, not just the GUI connectors."""
    with pytest.raises(CapabilityConflictError) as excinfo:
        solve(tag, reg)
    assert excinfo.value.missing == frozenset({"display"})
