"""Tests for ``lib/manifest.py`` — TOML schema parsing.

Each of the 8 builtin plugins must load cleanly and surface its declared
fields. We also cover failure paths (missing required keys, kind/dir
mismatches) on synthesised manifests.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from sanity_gravity.plugins.manifest import (  # noqa: E402
    AnnounceSpec,
    ComposeOverlay,
    IdeSpec,
    ManifestError,
    PluginManifest,
    PortSpec,
    load_manifest,
)


PLUGINS_DIR = _REPO_ROOT / "plugins"


# ---------------------------------------------------------------------------
# All 8 builtin manifests: load + structural assertions.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind,slug",
    [
        ("agents", "ag"),
        ("agents", "gc"),
        ("agents", "cc"),
        ("desktops", "xfce"),
        ("desktops", "none"),
        ("connectors", "kasm"),
        ("connectors", "vnc"),
        ("connectors", "ssh"),
    ],
)
def test_load_each_builtin_manifest(kind, slug):
    """Every shipped plugin manifest parses, with consistent slug/kind."""
    path = PLUGINS_DIR / kind / slug / "manifest.toml"
    m = load_manifest(path)

    assert isinstance(m, PluginManifest)
    assert m.slug == slug
    # kind=singular in manifest, kind=plural in directory tree
    assert m.kind == kind.rstrip("s")
    assert m.api_version == "1"
    assert m.dockerfile == "Dockerfile"
    assert m.dockerfile_path.is_file()


def test_ag_requires_display():
    m = load_manifest(PLUGINS_DIR / "agents" / "ag" / "manifest.toml")
    assert m.requires == ("display",)
    assert m.provides == ("ide",)


def test_xfce_provides_display():
    m = load_manifest(PLUGINS_DIR / "desktops" / "xfce" / "manifest.toml")
    assert m.provides == ("display",)
    assert m.requires == ()


def test_none_desktop_no_capabilities():
    m = load_manifest(PLUGINS_DIR / "desktops" / "none" / "manifest.toml")
    assert m.provides == ()
    assert m.requires == ()


def test_kasm_ports_and_compose():
    m = load_manifest(PLUGINS_DIR / "connectors" / "kasm" / "manifest.toml")
    assert m.provides == ("remote-gui",)
    assert m.requires == ("display",)
    by_label = m.ports_by_label()
    assert by_label["http"] == PortSpec(
        label="http", internal=8444, default=8444, env_var="KASM_PORT",
        legacy_slug="kasm",
    )
    assert by_label["ssh"].internal == 22
    assert by_label["ssh"].legacy_slug == "ssh"
    assert m.compose == ComposeOverlay(
        shm_size="512m", restart="unless-stopped", stop_grace_period="30s"
    )
    assert m.environment == ()
    assert isinstance(m.announce, AnnounceSpec)
    # template carries the {ports.http} substitution placeholder
    assert "{ports.http}" in m.announce.template


def test_vnc_environment_includes_vnc_pw():
    m = load_manifest(PLUGINS_DIR / "connectors" / "vnc" / "manifest.toml")
    env = dict(m.environment)
    assert "VNC_PW" in env
    assert "VNC_RESOLUTION" in env
    assert "VNC_DEPTH" in env
    by_label = m.ports_by_label()
    assert set(by_label) == {"vnc", "novnc", "ssh"}


def test_ssh_announce_uses_sanity_cli_shell():
    m = load_manifest(PLUGINS_DIR / "connectors" / "ssh" / "manifest.toml")
    assert m.compose.is_empty()
    assert m.environment == ()
    # The Shell hint points at the supported entry point, not docker exec.
    assert "./sanity-cli shell --name {project}" in m.announce.template
    assert "docker exec" not in m.announce.template


# ---------------------------------------------------------------------------
# Failure paths.
# ---------------------------------------------------------------------------


def _write(tmp_path, body: str) -> Path:
    p = tmp_path / "manifest.toml"
    p.write_text(body)
    return p


def test_missing_plugin_table_raises(tmp_path):
    path = _write(tmp_path, '[capabilities]\nprovides = []\n')
    with pytest.raises(ManifestError, match="missing required key 'plugin'"):
        load_manifest(path)


def test_invalid_kind_rejected(tmp_path):
    path = _write(
        tmp_path,
        '[plugin]\nslug = "x"\nname = "x"\nkind = "weapon"\napi_version = "1"\n'
        '[build]\ndockerfile = "Dockerfile"\n',
    )
    with pytest.raises(ManifestError, match="kind must be one of"):
        load_manifest(path)


def test_agent_can_declare_ports():
    """Symmetric schema: any kind may declare [ports.<label>]."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write(
            Path(td),
            '[plugin]\nslug = "x"\nname = "x"\nkind = "agent"\napi_version = "1"\n'
            '[build]\ndockerfile = "Dockerfile"\n'
            '[ports.web]\ninternal = 80\ndefault = 8080\nenv_var = "WEB_PORT"\n',
        )
        m = load_manifest(path)
    assert m.kind == "agent"
    assert m.ports_by_label()["web"] == PortSpec(
        label="web", internal=80, default=8080, env_var="WEB_PORT"
    )


def test_desktop_can_declare_announce():
    """Symmetric schema: any kind may declare [announce]."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write(
            Path(td),
            '[plugin]\nslug = "x"\nname = "x"\nkind = "desktop"\napi_version = "1"\n'
            '[build]\ndockerfile = "Dockerfile"\n'
            '[announce]\ntemplate = "Resolution: 1920x1080"\n',
        )
        m = load_manifest(path)
    assert m.kind == "desktop"
    assert isinstance(m.announce, AnnounceSpec)
    assert "1920x1080" in m.announce.template


def test_agent_can_declare_environment():
    """Symmetric schema: any kind may declare [environment]."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write(
            Path(td),
            '[plugin]\nslug = "x"\nname = "x"\nkind = "agent"\napi_version = "1"\n'
            '[build]\ndockerfile = "Dockerfile"\n'
            '[environment]\nOPENAI_API_KEY = "${OPENAI_API_KEY:-}"\n',
        )
        m = load_manifest(path)
    assert m.kind == "agent"
    env = dict(m.environment)
    assert env["OPENAI_API_KEY"] == "${OPENAI_API_KEY:-}"


def test_desktop_can_declare_compose_overlay():
    """Symmetric schema: any kind may declare [compose]."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write(
            Path(td),
            '[plugin]\nslug = "x"\nname = "x"\nkind = "desktop"\napi_version = "1"\n'
            '[build]\ndockerfile = "Dockerfile"\n'
            '[compose]\nshm_size = "1g"\n',
        )
        m = load_manifest(path)
    assert m.kind == "desktop"
    assert m.compose.shm_size == "1g"


def test_missing_dockerfile_key_rejected(tmp_path):
    path = _write(
        tmp_path,
        '[plugin]\nslug = "x"\nname = "x"\nkind = "agent"\napi_version = "1"\n'
        '[build]\n',
    )
    with pytest.raises(ManifestError, match="missing required key 'dockerfile'"):
        load_manifest(path)


def test_nonexistent_file(tmp_path):
    with pytest.raises(ManifestError, match="manifest not found"):
        load_manifest(tmp_path / "nope.toml")


# ---------------------------------------------------------------------------
# Malformed TOML / api_version / source_path-derived attribute paths.
# ---------------------------------------------------------------------------


def test_malformed_toml_unclosed_table_wrapped(tmp_path):
    """A genuine TOML parse error must surface as ``ManifestError`` —
    not a raw ``tomllib.TOMLDecodeError`` — with the manifest path in
    the message so the user knows which file to fix."""
    path = _write(tmp_path, "[plugin\nslug = \"oops\"\n")
    with pytest.raises(ManifestError, match="TOML parse error") as excinfo:
        load_manifest(path)
    assert str(path) in str(excinfo.value)


def test_malformed_toml_duplicate_key_wrapped(tmp_path):
    path = _write(
        tmp_path,
        '[plugin]\nslug = "a"\nslug = "b"\nname = "x"\nkind = "agent"\napi_version = "1"\n'
        '[build]\ndockerfile = "Dockerfile"\n',
    )
    with pytest.raises(ManifestError, match="TOML parse error"):
        load_manifest(path)


def test_unknown_api_version_rejected(tmp_path):
    """Future / unknown api_version must fail closed: silently loading
    a plugin that targets a different schema is a recipe for bugs."""
    path = _write(
        tmp_path,
        '[plugin]\nslug = "x"\nname = "x"\nkind = "agent"\napi_version = "99"\n'
        '[build]\ndockerfile = "Dockerfile"\n',
    )
    with pytest.raises(ManifestError, match="api_version"):
        load_manifest(path)


def test_dockerfile_path_without_source_path_raises():
    """In-memory manifests have no ``source_path`` and must therefore
    raise on path-derived attributes rather than yield a misleading
    relative path."""
    m = PluginManifest(
        slug="x", name="x", kind="agent", api_version="1",
        provides=(), requires=(), dockerfile="Dockerfile",
    )
    with pytest.raises(ManifestError, match="source_path"):
        _ = m.dockerfile_path
    with pytest.raises(ManifestError, match="source_path"):
        _ = m.dir


def test_ag_declares_ide_maintenance():
    """The ag agent carries the [ide] contract the ide verb consumes."""
    m = load_manifest(PLUGINS_DIR / "agents" / "ag" / "manifest.toml")
    assert m.ide == IdeSpec(
        command=("/usr/local/bin/gravity-cli", "ide"),
        inject=(
            "usr/local/bin/gravity-cli",
            "usr/local/bin/chrome-cleanup.sh",
        ),
    )
    # Every injected file must actually exist under the plugin's rootfs.
    for rel in m.ide.inject:
        assert (m.dir / "rootfs" / rel).is_file()


def test_ide_section_optional():
    """Agents without an IDE simply omit [ide]."""
    m = load_manifest(PLUGINS_DIR / "agents" / "cc" / "manifest.toml")
    assert m.ide is None


def test_ide_inject_defaults_empty(tmp_path):
    path = _write(
        tmp_path,
        '[plugin]\nslug = "x"\nname = "x"\nkind = "agent"\napi_version = "1"\n'
        '[build]\ndockerfile = "Dockerfile"\n'
        '[ide]\ncommand = ["/usr/bin/tool", "ide"]\n',
    )
    m = load_manifest(path)
    assert m.ide == IdeSpec(command=("/usr/bin/tool", "ide"), inject=())


def test_ide_missing_command_rejected(tmp_path):
    path = _write(
        tmp_path,
        '[plugin]\nslug = "x"\nname = "x"\nkind = "agent"\napi_version = "1"\n'
        '[build]\ndockerfile = "Dockerfile"\n'
        '[ide]\ninject = ["usr/bin/tool"]\n',
    )
    with pytest.raises(ManifestError, match="missing required key 'command'"):
        load_manifest(path)


def test_ide_empty_command_rejected(tmp_path):
    path = _write(
        tmp_path,
        '[plugin]\nslug = "x"\nname = "x"\nkind = "agent"\napi_version = "1"\n'
        '[build]\ndockerfile = "Dockerfile"\n'
        '[ide]\ncommand = []\n',
    )
    with pytest.raises(ManifestError, match="command"):
        load_manifest(path)


@pytest.mark.parametrize("bad", ["/usr/bin/tool", "../escape/tool"])
def test_ide_inject_must_be_rootfs_relative(tmp_path, bad):
    """Absolute or traversing inject paths would escape the plugin's
    rootfs/ tree; the loader must fail closed."""
    path = _write(
        tmp_path,
        '[plugin]\nslug = "x"\nname = "x"\nkind = "agent"\napi_version = "1"\n'
        '[build]\ndockerfile = "Dockerfile"\n'
        f'[ide]\ncommand = ["/usr/bin/tool"]\ninject = ["{bad}"]\n',
    )
    with pytest.raises(ManifestError, match="rootfs-relative"):
        load_manifest(path)


def test_port_legacy_slug_optional(tmp_path):
    """``legacy_slug`` defaults to None and can be set per-port."""
    path = _write(
        tmp_path,
        '[plugin]\nslug = "x"\nname = "x"\nkind = "connector"\napi_version = "1"\n'
        '[build]\ndockerfile = "Dockerfile"\n'
        '[ports.unlabelled]\ninternal = 22\ndefault = 2222\nenv_var = "X_PORT"\n'
        '[ports.tagged]\ninternal = 80\ndefault = 8080\nenv_var = "HTTP_PORT"\n'
        'legacy_slug = "http"\n',
    )
    m = load_manifest(path)
    by_label = m.ports_by_label()
    assert by_label["unlabelled"].legacy_slug is None
    assert by_label["tagged"].legacy_slug == "http"
