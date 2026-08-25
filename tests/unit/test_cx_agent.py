"""Unit tests for the ``cx`` (OpenAI Codex CLI) agent plugin.

The agent slug is the 2-char ``cx``; the installed binary is still
``codex``. These tests exercise only the plugin's manifest and its
interaction with the manifest-driven kernel (registry discovery,
capability solver, compose env passthrough). No Docker is involved --
the container-side install is covered by
``tests/integration/test_cx_agent.py``.
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

# The four combinations a pure-CLI agent (no GUI requirement) yields:
# every desktop/connector pair that itself satisfies the display rule.
CX_VALID_TAGS = [
    Tag("cx", "xfce", "kasm"),
    Tag("cx", "xfce", "ssh"),
    Tag("cx", "xfce", "vnc"),
    Tag("cx", "none", "ssh"),
]


@pytest.fixture(scope="module")
def reg() -> PluginRegistry:
    """Cold-load the builtin registry from the on-disk plugin tree."""
    reset_default_registry()
    return default_registry(PLUGINS_DIR)


# -- discovery ----------------------------------------------------------


def test_cx_is_discovered(reg):
    """The registry walks ``plugins/agents/cx/`` with no code changes."""
    assert "cx" in reg.agents


def test_cx_manifest_identity(reg):
    m = reg.agents["cx"]
    assert m.slug == "cx"
    assert m.name == "codex-cli"
    assert m.kind == "agent"
    assert m.api_version == "1"


def test_cx_is_pure_cli_agent(reg):
    """cx needs no GUI: it provides and requires nothing."""
    m = reg.agents["cx"]
    assert m.provides == ()
    assert m.requires == ()


def test_cx_injects_no_host_env(reg):
    """The sandbox must not auto-leak host secrets: cx declares no env,
    same as the other CLI agents. Auth is via in-container `codex login`."""
    assert reg.agents["cx"].environment == ()


# -- capability solving -------------------------------------------------


@pytest.mark.parametrize("tag", CX_VALID_TAGS, ids=lambda t: str(t))
def test_cx_valid_tags_pass(tag, reg):
    assert solve(tag, reg) == tag


def test_cx_appears_in_valid_tags(reg):
    assert set(CX_VALID_TAGS).issubset(set(reg.valid_tags()))


def test_cx_none_kasm_fails(reg):
    """A GUI connector still needs a display, even for a headless agent."""
    with pytest.raises(CapabilityConflictError) as excinfo:
        solve(Tag("cx", "none", "kasm"), reg)
    assert excinfo.value.missing == frozenset({"display"})


def test_cx_none_vnc_fails(reg):
    with pytest.raises(CapabilityConflictError):
        solve(Tag("cx", "none", "vnc"), reg)


