"""Unit tests for the ``dsh`` (DeepSeek Harness) agent plugin.

The agent slug matches the upstream launcher binary ``dsh``. Upstream is
a developer preview (rc-only releases), so the plugin lands at
``tier = "community"``: locally buildable, never in the CI/publish
matrix. These tests exercise only the manifest and its interaction with
the manifest-driven kernel (registry discovery, capability solver, tier
enumeration). No Docker is involved -- the container-side install is
covered by ``tests/integration/test_dsh_agent.py``.
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
# headless mode needs no display, and the web profile is reached through
# an ssh tunnel or the in-container browser, so dsh must not require one.
DSH_VALID_TAGS = [
    Tag("dsh", "xfce", "kasm"),
    Tag("dsh", "xfce", "ssh"),
    Tag("dsh", "xfce", "vnc"),
    Tag("dsh", "none", "ssh"),
]


@pytest.fixture(scope="module")
def reg() -> PluginRegistry:
    """Cold-load the builtin registry from the on-disk plugin tree."""
    reset_default_registry()
    return default_registry(PLUGINS_DIR)


# -- discovery ----------------------------------------------------------


def test_dsh_is_discovered(reg):
    """The registry walks ``plugins/agents/dsh/`` with no code changes."""
    assert "dsh" in reg.agents


def test_dsh_manifest_identity(reg):
    m = reg.agents["dsh"]
    assert m.slug == "dsh"
    assert m.name == "deepseek-harness"
    assert m.kind == "agent"
    assert m.api_version == "1"


def test_dsh_is_pure_cli_agent(reg):
    """dsh needs no GUI: both its profiles work without a display."""
    m = reg.agents["dsh"]
    assert m.provides == ()
    assert m.requires == ()


def test_dsh_injects_no_host_env(reg):
    """The sandbox must not auto-leak host secrets: dsh declares no env,
    same as the other CLI agents. Auth is in-container only --
    DEEPSEEK_API_KEY or $DSH_HOME/.env."""
    assert reg.agents["dsh"].environment == ()


def test_dsh_declares_no_ports(reg):
    """The web profile binds 127.0.0.1:3080 and upstream's CLI refuses
    0.0.0.0, so a port mapping could never carry traffic; access is
    documented as `ssh -L` (or the in-container browser on xfce)."""
    assert reg.agents["dsh"].ports == ()


# -- tier ---------------------------------------------------------------


def test_dsh_is_community(reg):
    """Upstream guarantees compatibility-breaking changes (developer
    preview, rc-only); community tier keeps it out of CI/publish while
    staying locally buildable."""
    assert reg.agents["dsh"].tier == "community"


def test_dsh_tags_stay_out_of_the_official_matrix():
    """Community tier: dsh-* tags parse and build locally but must not
    enter OFFICIAL_TAGS (the `list --json` source CI enumerates its
    matrices from), and the official matrix size must not move."""
    from sanity_gravity.core.registry import (
        OFFICIAL_TAGS,
        VALID_TAGS,
        resolve_tag,
        tag_tier,
    )

    assert not any(resolve_tag(t).agent == "dsh" for t in OFFICIAL_TAGS)
    assert len(OFFICIAL_TAGS) == 19

    dsh_tags = [t for t in VALID_TAGS if resolve_tag(t).agent == "dsh"]
    assert sorted(dsh_tags) == [
        "dsh-lxqt-kasm", "dsh-lxqt-ssh", "dsh-lxqt-vnc",
        "dsh-none-ssh",
        "dsh-openbox-kasm", "dsh-openbox-ssh", "dsh-openbox-vnc",
        "dsh-xfce-kasm", "dsh-xfce-ssh", "dsh-xfce-vnc",
    ]
    for t in dsh_tags:
        assert tag_tier(resolve_tag(t)) == "community"


# -- capability solving -------------------------------------------------


@pytest.mark.parametrize("tag", DSH_VALID_TAGS, ids=lambda t: str(t))
def test_dsh_valid_tags_pass(tag, reg):
    assert solve(tag, reg) == tag


def test_dsh_appears_in_valid_tags(reg):
    assert set(DSH_VALID_TAGS).issubset(set(reg.valid_tags()))


def test_dsh_none_kasm_fails(reg):
    """A GUI connector still needs a display, even for a headless agent."""
    with pytest.raises(CapabilityConflictError) as excinfo:
        solve(Tag("dsh", "none", "kasm"), reg)
    assert excinfo.value.missing == frozenset({"display"})


def test_dsh_none_vnc_fails(reg):
    with pytest.raises(CapabilityConflictError):
        solve(Tag("dsh", "none", "vnc"), reg)


# -- install pinning ----------------------------------------------------


def test_dsh_requirements_are_fully_hash_pinned():
    """Upstream is an rc-only developer preview: the pip route is chosen
    exactly because PyPI publishes per-wheel sha256 for both x86_64 and
    aarch64, so --require-hashes turns any upstream tamper or silent
    re-upload into a build failure. Every requirement line must be an
    exact ``==`` pin and every package must carry at least one hash."""
    req = (PLUGINS_DIR / "agents" / "dsh" / "requirements.txt").read_text()
    lines = [
        line.strip() for line in req.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    joined = " ".join(lines)
    for pkg in ("deepseek-harness-sdk==0.1.5rc1",
                "deepseek-harness-runtime-bin==0.1.5rc1"):
        assert pkg in joined, f"missing exact pin: {pkg}"
    # Both linux architectures must be able to satisfy --require-hashes.
    assert joined.count("--hash=sha256:") >= 3, (
        "expected hashes for the sdk wheel plus the x86_64 AND aarch64 "
        "runtime wheels"
    )
