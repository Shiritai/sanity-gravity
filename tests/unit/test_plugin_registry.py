"""Tests for ``lib/plugins.py`` registry discovery + tag enumeration."""
from __future__ import annotations

from pathlib import Path

import pytest


from sanity_gravity.plugins.manifest import ManifestError
from sanity_gravity.domain.tags import Tag
from sanity_gravity.plugins.registry import PluginRegistry

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


PLUGINS_DIR = _REPO_ROOT / "plugins"


# ---------------------------------------------------------------------------
# Builtin registry: the on-disk layout under ``plugins/``.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def reg() -> PluginRegistry:
    return PluginRegistry.from_dir(PLUGINS_DIR)


def test_from_dir_loads_plugins(reg):
    assert len(reg.agents) >= 3
    assert len(reg.desktops) >= 2
    assert len(reg.connectors) >= 3
    assert sum(len(b) for b in (reg.agents, reg.desktops, reg.connectors)) >= 8


def test_registered_slugs(reg):
    assert {"ag", "gc", "cc"}.issubset(set(reg.agents))
    assert set(reg.desktops) == {"xfce", "none"}
    assert set(reg.connectors) == {"kasm", "vnc", "ssh"}


def test_get_returns_manifest(reg):
    m = reg.get("connector", "kasm")
    assert m.slug == "kasm"
    assert m.kind == "connector"


def test_get_unknown_raises(reg):
    with pytest.raises(KeyError):
        reg.get("agent", "nope")


def test_valid_tags_returns_expected(reg):
    """The tag combinations PR #5's VALID_TAGS produced should still be present."""
    tags = reg.valid_tags()
    assert len(tags) >= 11
    expected = {
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
    }
    assert expected.issubset(set(tags))


def test_valid_tags_excludes_capability_conflicts(reg):
    """No headless+GUI-connector and no headless+ag combinations."""
    tags = reg.valid_tags()
    for t in tags:
        if t.desktop == "none":
            # Only headless agents with the ssh connector
            assert "display" not in reg.agents[t.agent].requires
            assert t.connector == "ssh"


# ---------------------------------------------------------------------------
# from_dir behaviour on synthetic trees.
# ---------------------------------------------------------------------------


def _write_plugin(root: Path, kind: str, slug: str, body: str) -> None:
    p = root / kind / slug
    p.mkdir(parents=True)
    (p / "manifest.toml").write_text(body)
    (p / "Dockerfile").write_text("FROM scratch\n")


def test_from_dir_skips_directory_without_manifest(tmp_path):
    """A plugin dir lacking ``manifest.toml`` is silently ignored."""
    (tmp_path / "agents" / "ghost").mkdir(parents=True)
    reg = PluginRegistry.from_dir(tmp_path)
    assert reg.agents == {}


def test_from_dir_rejects_kind_dir_mismatch(tmp_path):
    """A manifest declaring kind ≠ its parent directory must error."""
    _write_plugin(
        tmp_path,
        "agents",
        "ag2",
        '[plugin]\nslug = "ag2"\nname = "ag2"\nkind = "desktop"\napi_version = "1"\n'
        '[build]\ndockerfile = "Dockerfile"\n',
    )
    with pytest.raises(ManifestError, match="kind 'desktop' does not match"):
        PluginRegistry.from_dir(tmp_path)


def test_from_dir_rejects_slug_dir_mismatch(tmp_path):
    """A manifest's slug must match its directory name."""
    _write_plugin(
        tmp_path,
        "agents",
        "ag2",
        '[plugin]\nslug = "different"\nname = "x"\nkind = "agent"\napi_version = "1"\n'
        '[build]\ndockerfile = "Dockerfile"\n',
    )
    with pytest.raises(ManifestError, match="slug 'different' does not match"):
        PluginRegistry.from_dir(tmp_path)


def test_from_dir_empty_root_returns_empty_registry(tmp_path):
    reg = PluginRegistry.from_dir(tmp_path)
    assert reg.all_manifests() == []
    assert reg.valid_tags() == []


# ---------------------------------------------------------------------------
# [plugin].default invariants (load-time assertions).
# ---------------------------------------------------------------------------


_PIN = "debian:12-slim@sha256:" + "0" * 64


def _base_manifest(slug: str, default: bool = False) -> str:
    lines = [
        "[plugin]",
        f'slug = "{slug}"',
        f'name = "{slug} (base)"',
        'kind = "base-image"',
        'api_version = "1"',
    ]
    if default:
        lines.append("default = true")
    lines += ["[build]", 'dockerfile = "Dockerfile"', f'from = "{_PIN}"']
    return "\n".join(lines) + "\n"


_MINIMAL_AGENT = (
    '[plugin]\nslug = "%s"\nname = "x"\nkind = "agent"\napi_version = "1"\n'
    '[build]\ndockerfile = "Dockerfile"\n'
)


def test_two_defaults_in_one_kind_rejected(tmp_path):
    _write_plugin(
        tmp_path, "base-images", "ubuntu", _base_manifest("ubuntu", default=True)
    )
    _write_plugin(
        tmp_path, "base-images", "debian", _base_manifest("debian", default=True)
    )
    with pytest.raises(ManifestError, match="exactly one plugin may set"):
        PluginRegistry.from_dir(tmp_path)


def test_base_images_without_default_rejected(tmp_path):
    """An elidable kind with registered plugins but no default would
    leave elided tags unresolvable."""
    _write_plugin(tmp_path, "base-images", "ubuntu", _base_manifest("ubuntu"))
    with pytest.raises(
        ManifestError, match=r"no plugin with \[plugin\]\.default = true"
    ):
        PluginRegistry.from_dir(tmp_path)


def test_default_slug_returns_marked_plugin(tmp_path):
    _write_plugin(
        tmp_path, "base-images", "ubuntu", _base_manifest("ubuntu", default=True)
    )
    _write_plugin(tmp_path, "base-images", "debian", _base_manifest("debian"))
    reg = PluginRegistry.from_dir(tmp_path)
    assert reg.default_slug("base-image") == "ubuntu"
    assert set(reg.base_images) == {"ubuntu", "debian"}


def test_default_slug_without_default_raises(tmp_path):
    _write_plugin(tmp_path, "agents", "solo", _MINIMAL_AGENT % "solo")
    reg = PluginRegistry.from_dir(tmp_path)
    with pytest.raises(KeyError):
        reg.default_slug("agent")


def test_default_on_spelled_out_kind_rejected(tmp_path):
    """agent/desktop/connector are always spelled out in a tag; a
    default there is meaningless and must fail loudly."""
    _write_plugin(
        tmp_path,
        "agents",
        "solo",
        '[plugin]\nslug = "solo"\nname = "x"\nkind = "agent"\napi_version = "1"\n'
        "default = true\n"
        '[build]\ndockerfile = "Dockerfile"\n',
    )
    with pytest.raises(ManifestError, match="always spelled out"):
        PluginRegistry.from_dir(tmp_path)


def test_zero_base_image_plugins_load_fine(tmp_path):
    """Transition rule pin: an elidable kind must eventually carry
    exactly one default, but main has no base dimension in the tag
    grammar and ships zero base-image plugins - the invariant only
    binds once the kind has at least one registered plugin."""
    _write_plugin(tmp_path, "agents", "solo", _MINIMAL_AGENT % "solo")
    reg = PluginRegistry.from_dir(tmp_path)
    assert reg.base_images == {}
    assert set(reg.agents) == {"solo"}
