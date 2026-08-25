"""Tests for ``sanity_gravity/plugins/manifest.py`` — TOML schema parsing.

Three layers, deliberately kept apart:

* **builtin data shape** — the shipped manifests under ``plugins/``
  parse, and surface the fields the rest of the system reads;
* **synthesized positives** — the sections the schema declares
  symmetric (any kind may carry ports / announce / tier / ide);
* **the rejection table** — one row per distinct loader diagnostic.

The rejections are a table rather than one ``def`` per bad field
because those ``def``s share a production statement: flipping the
``or`` in ``load_manifest``'s ``[capabilities]`` lookup turned 21 of
them red at once, so 20 of those failures repeated what the first one
already said. A table row costs three lines and names its own
diagnostic, which is the part that carries information.

Every rejection goes through :func:`_assert_rejected`, which refuses a
pattern the manifest *path* already satisfies — see the note there. That
trap had silently disarmed four of these assertions.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from sanity_gravity.plugins.manifest import (
    TIERS,
    AnnounceSpec,
    ComposeOverlay,
    IdeSpec,
    ManifestError,
    PluginManifest,
    PortSpec,
    load_manifest,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


PLUGINS_DIR = _REPO_ROOT / "plugins"


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "manifest.toml"
    p.write_text(body)
    return p


# Fragments the synthesized manifests are assembled from. Keeping the
# valid halves in one place means a rejection row shows only the field
# it is actually about.
_PLUGIN = '[plugin]\nslug = "x"\nname = "x"\nkind = "agent"\napi_version = "1"\n'
_BUILD = '[build]\ndockerfile = "Dockerfile"\n'
_MINIMAL = _PLUGIN + _BUILD


# ---------------------------------------------------------------------------
# Builtin manifests: the data the rest of the system reads.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind,slug,name",
    [
        ("agents", "ag", "antigravity"),
        ("desktops", "xfce", "xfce"),
        ("connectors", "kasm", "KasmVNC"),
    ],
)
def test_load_each_builtin_manifest(kind, slug, name):
    """One shipped manifest per kind parses with consistent identity.

    Only one slug per kind: the remaining builtins are loaded by
    ``test_plugin_registry.py``'s ``from_dir`` scan (every manifest under
    ``plugins/``) and by the per-plugin assertions below, so extra
    parameters here re-run the same loader over near-identical data.
    """
    path = PLUGINS_DIR / kind / slug / "manifest.toml"
    m = load_manifest(path)

    assert isinstance(m, PluginManifest)
    assert m.slug == slug
    # kind=singular in manifest, kind=plural in directory tree
    assert m.kind == kind.rstrip("s")
    assert m.name == name
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


def test_gc_is_deprecated():
    """Gemini CLI is deprecated (see commit 08a284a): out of the CI
    matrix, still locally usable."""
    m = load_manifest(PLUGINS_DIR / "agents" / "gc" / "manifest.toml")
    assert m.tier == "deprecated"


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


# ---------------------------------------------------------------------------
# Synthesized positives: the symmetric optional sections, and defaults.
# ---------------------------------------------------------------------------


def test_lowercase_alphanumeric_slug_accepted(tmp_path):
    """The charset rule accepts digits after the leading letter."""
    body = _PLUGIN.replace('slug = "x"', 'slug = "xfce2"') + _BUILD
    assert load_manifest(_write(tmp_path, body)).slug == "xfce2"


def test_agent_can_declare_ports(tmp_path):
    """Symmetric schema: any kind may declare [ports.<label>].

    The PortSpec equality also pins ``legacy_slug``'s default of None,
    which is the half of the field a manifest never spells out.
    """
    path = _write(
        tmp_path,
        _MINIMAL + '[ports.web]\ninternal = 80\ndefault = 8080\nenv_var = "WEB_PORT"\n',
    )
    m = load_manifest(path)
    assert m.kind == "agent"
    assert m.ports_by_label()["web"] == PortSpec(
        label="web", internal=80, default=8080, env_var="WEB_PORT"
    )


def test_desktop_can_declare_announce(tmp_path):
    """Symmetric schema: any kind may declare [announce]."""
    path = _write(
        tmp_path,
        _PLUGIN.replace('kind = "agent"', 'kind = "desktop"') + _BUILD
        + '[announce]\ntemplate = "Resolution: 1920x1080"\n',
    )
    m = load_manifest(path)
    assert m.kind == "desktop"
    assert isinstance(m.announce, AnnounceSpec)
    assert "1920x1080" in m.announce.template


def test_ide_inject_defaults_empty(tmp_path):
    path = _write(tmp_path, _MINIMAL + '[ide]\ncommand = ["/usr/bin/tool", "ide"]\n')
    m = load_manifest(path)
    assert m.ide == IdeSpec(command=("/usr/bin/tool", "ide"), inject=())


def test_tier_defaults_to_official(tmp_path):
    """Existing manifests without [plugin].tier stay official."""
    assert load_manifest(_write(tmp_path, _MINIMAL)).tier == "official"


def test_tier_explicit_value_parsed(tmp_path):
    """An explicit tier is read from the manifest, not inferred."""
    path = _write(tmp_path, _PLUGIN + 'tier = "deprecated"\n' + _BUILD)
    assert load_manifest(path).tier == "deprecated"


def test_dockerfile_path_without_source_path_raises():
    """In-memory manifests have no ``source_path`` and must therefore
    raise on path-derived attributes rather than yield a misleading
    relative path."""
    m = PluginManifest(
        slug="x", name="x", kind="agent", api_version="1",
        provides=(), requires=(), dockerfile="Dockerfile",
    )
    with pytest.raises(ManifestError, match=r"path-derived attributes"):
        _ = m.dir
    # Matched on text only ``dockerfile_path``'s own guard produces:
    # without that guard the attribute falls through to ``self.dir``,
    # which raises a ManifestError naming ``source_path`` too — so the
    # obvious pattern would pass with the guard deleted.
    with pytest.raises(ManifestError, match=r"dockerfile_path is unavailable"):
        _ = m.dockerfile_path


# ---------------------------------------------------------------------------
# Rejections.
# ---------------------------------------------------------------------------


def _assert_rejected(path: Path, pattern: str) -> str:
    """Load ``path``, require a ManifestError matching ``pattern``.

    ``pytest.raises(match=...)`` runs ``re.search`` over the *whole*
    message, and every loader diagnostic embeds the manifest path — which
    under ``tmp_path`` is a directory named after the test. ``match=
    "reserved"`` was therefore satisfied by ``test_reserved_slug_base_
    reject0`` and stayed green with the word deleted from production.
    Rejecting a pattern the path already satisfies makes that class of
    always-true assertion impossible to write here.
    """
    assert not re.search(pattern, str(path)), (
        f"pattern {pattern!r} is satisfied by the manifest path itself "
        f"({path}); it would hold whatever the loader said"
    )
    with pytest.raises(ManifestError, match=pattern) as excinfo:
        load_manifest(path)
    return str(excinfo.value)


def _slug(slug: str) -> str:
    return f'[plugin]\nslug = "{slug}"\nname = "x"\nkind = "agent"\napi_version = "1"\n'


_MISSING_KEY = "missing required key"
_SLUG_RULE = r"\[plugin\]\.slug must match"

_REJECTIONS = [
    # -- required keys ----------------------------------------------------
    pytest.param('[capabilities]\nprovides = []\n',
                 rf"{_MISSING_KEY} 'plugin'", id="no-plugin-table"),
    pytest.param('[plugin]\nname = "x"\nkind = "agent"\napi_version = "1"\n' + _BUILD,
                 rf"{_MISSING_KEY} 'slug'", id="no-plugin-slug"),
    pytest.param('[plugin]\nslug = "x"\nkind = "agent"\napi_version = "1"\n' + _BUILD,
                 rf"{_MISSING_KEY} 'name'", id="no-plugin-name"),
    pytest.param('[plugin]\nslug = "x"\nname = "x"\napi_version = "1"\n' + _BUILD,
                 rf"{_MISSING_KEY} 'kind'", id="no-plugin-kind"),
    pytest.param('[plugin]\nslug = "x"\nname = "x"\nkind = "agent"\n' + _BUILD,
                 rf"{_MISSING_KEY} 'api_version'", id="no-plugin-api-version"),
    pytest.param(_PLUGIN, rf"{_MISSING_KEY} 'build'", id="no-build-table"),
    pytest.param(_PLUGIN + '[build]\n',
                 rf"{_MISSING_KEY} 'dockerfile'", id="no-build-dockerfile"),
    pytest.param(_MINIMAL + '[ports.web]\ndefault = 8080\nenv_var = "WEB_PORT"\n',
                 rf"{_MISSING_KEY} 'internal'", id="no-port-internal"),
    pytest.param(_MINIMAL + '[ports.web]\ninternal = 80\nenv_var = "WEB_PORT"\n',
                 rf"{_MISSING_KEY} 'default'", id="no-port-default"),
    pytest.param(_MINIMAL + '[ports.web]\ninternal = 80\ndefault = 8080\n',
                 rf"{_MISSING_KEY} 'env_var'", id="no-port-env-var"),
    pytest.param(_MINIMAL + '[announce]\nblurb = "hi"\n',
                 rf"{_MISSING_KEY} 'template'", id="no-announce-template"),
    pytest.param(_MINIMAL + '[ide]\ninject = ["usr/bin/tool"]\n',
                 rf"{_MISSING_KEY} 'command'", id="no-ide-command"),
    # -- a section that is not a table ------------------------------------
    pytest.param('plugin = 5\n' + _BUILD,
                 r"\[plugin\] must be a table", id="plugin-is-scalar"),
    pytest.param('build = 5\n' + _PLUGIN,
                 r"\[build\] must be a table", id="build-is-scalar"),
    pytest.param('ports = 5\n' + _MINIMAL,
                 r"\[ports\]: expected table", id="ports-is-scalar"),
    pytest.param(_MINIMAL + '[ports]\nweb = 5\n',
                 r"\[ports\]\.web: expected table", id="port-entry-is-scalar"),
    # -- scalar type guards -----------------------------------------------
    pytest.param(_MINIMAL + '[capabilities]\nprovides = "http-gui"\n',
                 r"\[capabilities\]\.provides: expected list, got str",
                 id="provides-is-scalar"),
    pytest.param(_MINIMAL + '[capabilities]\nprovides = [1]\n',
                 r"\[capabilities\]\.provides\[0\]: expected string, got int",
                 id="provides-item-is-int"),
    pytest.param(_MINIMAL + '[capabilities]\nrequires = "display"\n',
                 r"\[capabilities\]\.requires: expected list, got str",
                 id="requires-is-scalar"),
    pytest.param(
        _MINIMAL + '[ports.web]\ninternal = "80"\ndefault = 8080\nenv_var = "W"\n',
        r"\.internal: expected int, got str", id="port-internal-is-str"),
    # bools are ints in python; the loader rejects them explicitly, so a
    # manifest cannot smuggle `internal = true` past the type check.
    pytest.param(
        _MINIMAL + '[ports.web]\ninternal = true\ndefault = 8080\nenv_var = "W"\n',
        r"\.internal: expected int, got bool", id="port-internal-is-bool"),
    pytest.param(_PLUGIN + 'tier = 1\n' + _BUILD,
                 r"\[plugin\]\.tier: expected string, got int", id="tier-is-int"),
    # -- value rules ------------------------------------------------------
    pytest.param('[plugin]\nslug = "x"\nname = "x"\nkind = "weapon"\napi_version = "1"\n'
                 + _BUILD,
                 r"\[plugin\]\.kind must be one of", id="kind-not-a-kind"),
    # One row per way of violating ^[a-z][a-z0-9]*$: each catches a
    # different loosening of the pattern and none catches another's.
    pytest.param(_slug("arch_linux") + _BUILD, _SLUG_RULE, id="slug-underscore"),
    pytest.param(_slug("rocky-9") + _BUILD, _SLUG_RULE, id="slug-hyphen"),
    pytest.param(_slug("9lives") + _BUILD, _SLUG_RULE, id="slug-leading-digit"),
    pytest.param(_slug("Xfce") + _BUILD, _SLUG_RULE, id="slug-uppercase"),
    pytest.param(_slug("") + _BUILD, _SLUG_RULE, id="slug-empty"),
    # 'base' is reserved by the layer-name grammar: slug 'base' renders
    # '_base-<desktop>', colliding with the desktop layer's own name.
    # RESERVED_SLUGS is checked kind-independently, so one kind suffices.
    pytest.param(_slug("base") + _BUILD,
                 r"slug 'base' is reserved", id="slug-reserved"),
    pytest.param(_PLUGIN.replace('api_version = "1"', 'api_version = "99"') + _BUILD,
                 r"api_version '99' is not supported", id="api-version-unknown"),
    pytest.param(_MINIMAL + '[ide]\ncommand = []\n',
                 r"\[ide\]\.command: must not be empty", id="ide-command-empty"),
    # Absolute and traversing inject paths escape the plugin's rootfs/
    # tree by different halves of the same guard, so both stay.
    pytest.param(_MINIMAL + '[ide]\ncommand = ["/usr/bin/tool"]\ninject = ["/usr/bin/tool"]\n',
                 r"must be a rootfs-relative path", id="ide-inject-absolute"),
    pytest.param(_MINIMAL + '[ide]\ncommand = ["/usr/bin/tool"]\ninject = ["../escape/tool"]\n',
                 r"must be a rootfs-relative path", id="ide-inject-traversal"),
]


@pytest.mark.parametrize("body,pattern", _REJECTIONS)
def test_manifest_rejects(tmp_path, body, pattern):
    """Every schema violation fails closed, naming the offending field."""
    _assert_rejected(_write(tmp_path, body), pattern)


# ---------------------------------------------------------------------------
# Rejections whose *message quality* is the point, not just the rejection.
# ---------------------------------------------------------------------------


def test_nonexistent_file(tmp_path):
    with pytest.raises(ManifestError, match="manifest not found"):
        load_manifest(tmp_path / "nope.toml")


def test_malformed_toml_wrapped_with_offending_path(tmp_path):
    """A genuine TOML parse error must surface as ``ManifestError`` —
    not a raw ``tomllib.TOMLDecodeError`` — with the manifest path in
    the message so the user knows which file to fix."""
    path = _write(tmp_path, '[plugin\nslug = "oops"\n')
    assert str(path) in _assert_rejected(path, r"TOML parse error")


def test_invalid_tier_message_names_every_accepted_tier(tmp_path):
    """Unknown tier names fail closed, naming the closed set so the
    author can fix the manifest without reading the loader."""
    msg = _assert_rejected(
        _write(tmp_path, _PLUGIN + 'tier = "legacy"\n' + _BUILD),
        r"\[plugin\]\.tier must be one of",
    )
    for accepted in TIERS:
        assert accepted in msg


def test_near_miss_api_version_gets_an_exact_string_hint(tmp_path):
    """``1.0`` / ``v1`` read as ``1`` to humans but are different
    strings; the diagnostic has to say so or the author edits blind."""
    for near_miss in ("1.0", "v1"):
        body = _PLUGIN.replace('api_version = "1"', f'api_version = "{near_miss}"')
        msg = _assert_rejected(
            _write(tmp_path, body + _BUILD),
            rf"api_version '{re.escape(near_miss)}' is not supported",
        )
        assert 'try api_version = "1"' in msg
