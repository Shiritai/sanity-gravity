"""Unit tests for the ``ocd`` (OpenCode Desktop) agent plugin.

The agent slug is the 3-char ``ocd``; the installed app is the OpenCode
Desktop Electron build under ``/opt/OpenCode``. Unlike the ``oc`` CLI
plugin, ``ocd`` is a GUI agent: it declares ``requires = ["display"]``, so
only desktops that provide a display form valid tags. These tests
exercise only the plugin's manifest and its interaction with the
manifest-driven kernel (registry discovery, capability solver, tier
enumeration). No Docker is involved -- the container-side install is a
plain apt/curl step guarded by the pinned version + SHA256 checksums in
the Dockerfile.

The full ocd-* tag list is derived (``_ocd_valid_tags``) rather than
spelled out: a hardcoded list silently stops growing the moment a new
GUI desktop lands, since ``issubset``/``in`` checks against a stale list
still pass. ``OCD_KNOWN_TAGS`` stays a literal on purpose -- it is the
anchor that has to solve on its own, independent of whatever the
derivation computes.
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

# Spot-check literal, deliberately NOT the full list: one desktop kind
# each. If a broken derivation (or a `solve` that stopped checking
# anything) let every tag through, these three still have to pass on
# their own. Touching this requires an existing desktop being renamed or
# dropped -- a new desktop landing does not.
OCD_KNOWN_TAGS = [
    Tag("ocd", "xfce", "kasm"),
    Tag("ocd", "lxqt", "vnc"),
    Tag("ocd", "openbox", "ssh"),
]


def _gui_desktops(registry: PluginRegistry) -> list[str]:
    """Desktop slugs that provide a display, in registry order.

    A landing desktop needs no edit here: it is picked up the moment its
    manifest's ``provides`` lists ``display``.
    """
    return [slug for slug, m in registry.desktops.items() if "display" in m.provides]


def _ocd_valid_tags(registry: PluginRegistry) -> list[Tag]:
    """ocd's valid tags: every GUI desktop crossed with every connector.

    ocd requires ``display`` and provides nothing, so a GUI desktop is
    the only thing that can satisfy it -- and because a GUI desktop also
    covers kasm/vnc's own ``display`` requirement, every connector
    clears the solver on it. The ``solve`` call is the real check here,
    not a formality: it is what would catch a connector that grew a
    requirement no GUI desktop here provides.
    """
    tags = []
    for d in _gui_desktops(registry):
        for c in registry.connectors:
            tag = Tag("ocd", d, c)
            try:
                solve(tag, registry)
            except CapabilityConflictError:
                continue
            tags.append(tag)
    return tags


@pytest.fixture(scope="module")
def reg() -> PluginRegistry:
    """Cold-load the builtin registry from the on-disk plugin tree."""
    reset_default_registry()
    return default_registry(PLUGINS_DIR)


@pytest.fixture(scope="module")
def ocd_valid_tags(reg) -> list[Tag]:
    return _ocd_valid_tags(reg)


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


def test_ocd_tags_stay_out_of_the_official_matrix(ocd_valid_tags):
    """Every ocd tag reaches VALID_TAGS but none reaches OFFICIAL_TAGS
    (the `list --json` source CI enumerates its matrices from) -- ocd is
    community tier, so the whole tag is tainted regardless of desktop."""
    from sanity_gravity.core.registry import (
        OFFICIAL_TAGS,
        VALID_TAGS,
        resolve_tag,
        tag_tier,
    )

    assert [t for t in OFFICIAL_TAGS if resolve_tag(t).agent == "ocd"] == []
    ocd_tags = {t for t in VALID_TAGS if resolve_tag(t).agent == "ocd"}
    assert ocd_tags == {str(t) for t in ocd_valid_tags}
    for t in ocd_tags:
        assert tag_tier(resolve_tag(t)) == "community"


# -- capability solving -------------------------------------------------


@pytest.mark.parametrize("tag", OCD_KNOWN_TAGS, ids=lambda t: str(t))
def test_ocd_known_tags_pass(tag, reg):
    assert solve(tag, reg) == tag


def test_ocd_known_tags_are_a_subset_of_the_derived_valid_tags(ocd_valid_tags):
    assert set(OCD_KNOWN_TAGS).issubset(set(ocd_valid_tags))


def test_ocd_valid_tags_count_is_gui_desktops_times_connectors(reg, ocd_valid_tags):
    """Count invariant, not a magic number: one tag per (GUI desktop,
    connector) pair. Moves on its own as desktops or connectors are
    added or removed -- nothing here to keep in sync by hand."""
    assert len(ocd_valid_tags) == len(_gui_desktops(reg)) * len(reg.connectors)


def test_ocd_appears_in_valid_tags(reg, ocd_valid_tags):
    assert set(ocd_valid_tags).issubset(set(reg.valid_tags()))


@pytest.mark.parametrize(
    "tag", [Tag("ocd", "none", "kasm"), Tag("ocd", "none", "vnc"), Tag("ocd", "none", "ssh")]
)
def test_ocd_headless_tags_fail(tag, reg):
    """The desktop app cannot run headless: every none-* combo fails on
    the missing display, not just the GUI connectors."""
    with pytest.raises(CapabilityConflictError) as excinfo:
        solve(tag, reg)
    assert excinfo.value.missing == frozenset({"display"})
