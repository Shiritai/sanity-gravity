"""Tests for ``lib/manifest.py`` — TOML schema parsing.

Each of the 8 builtin plugins must load cleanly and surface its declared
fields. We also cover failure paths (missing required keys, kind/dir
mismatches) on synthesised manifests.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st


from sanity_gravity.plugins.manifest import (
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


@pytest.mark.parametrize("slug", ["arch_linux", "rocky-9", "9lives", "Xfce", ""])
def test_slug_outside_charset_rejected(tmp_path, slug):
    """Slugs are embedded in tag and layer-name grammars that reserve
    '-' (tag separator) and '_' (layer-name prefix); a slug containing
    either round-trips into strings the parsers cannot split back.
    Fail at load time, where the message can point at the manifest."""
    path = _write(
        tmp_path,
        f'[plugin]\nslug = "{slug}"\nname = "x"\nkind = "agent"\napi_version = "1"\n'
        '[build]\ndockerfile = "Dockerfile"\n',
    )
    with pytest.raises(ManifestError, match=r"\[plugin\].slug"):
        load_manifest(path)


@pytest.mark.parametrize("slug", ["x", "xfce", "xfce2"])
def test_lowercase_alphanumeric_slug_accepted(tmp_path, slug):
    path = _write(
        tmp_path,
        f'[plugin]\nslug = "{slug}"\nname = "x"\nkind = "agent"\napi_version = "1"\n'
        '[build]\ndockerfile = "Dockerfile"\n',
    )
    assert load_manifest(path).slug == slug


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


# ---------------------------------------------------------------------------
# Tier field.
# ---------------------------------------------------------------------------


_MINIMAL_AGENT = (
    '[plugin]\nslug = "x"\nname = "x"\nkind = "agent"\napi_version = "1"\n'
)


def test_tier_defaults_to_official(tmp_path):
    """Existing manifests without [plugin].tier stay official."""
    path = _write(tmp_path, _MINIMAL_AGENT + '[build]\ndockerfile = "Dockerfile"\n')
    m = load_manifest(path)
    assert m.tier == "official"


def test_gc_is_deprecated():
    """Gemini CLI is deprecated (see commit 08a284a): out of the CI
    matrix, still locally usable."""
    m = load_manifest(PLUGINS_DIR / "agents" / "gc" / "manifest.toml")
    assert m.tier == "deprecated"


@pytest.mark.parametrize("tier", ["official", "community", "deprecated"])
def test_tier_explicit_value_parsed(tmp_path, tier):
    path = _write(
        tmp_path,
        _MINIMAL_AGENT + f'tier = "{tier}"\n[build]\ndockerfile = "Dockerfile"\n',
    )
    m = load_manifest(path)
    assert m.tier == tier


def test_tier_invalid_value_rejected(tmp_path):
    """Unknown tier names must fail closed, naming the accepted values."""
    path = _write(
        tmp_path,
        _MINIMAL_AGENT + 'tier = "legacy"\n[build]\ndockerfile = "Dockerfile"\n',
    )
    with pytest.raises(ManifestError, match="tier") as excinfo:
        load_manifest(path)
    for accepted in ("official", "community", "deprecated"):
        assert accepted in str(excinfo.value)


def test_tier_wrong_type_rejected(tmp_path):
    path = _write(
        tmp_path,
        _MINIMAL_AGENT + 'tier = 1\n[build]\ndockerfile = "Dockerfile"\n',
    )
    with pytest.raises(ManifestError, match="expected string"):
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


@pytest.mark.parametrize("kind", ["agent", "desktop", "connector"])
def test_reserved_slug_base_rejected(tmp_path, kind):
    """'base' is reserved by the layer-name grammar: an agent slug
    'base' renders '_base-<desktop>', colliding with the desktop
    layer's name. Reserved across all kinds for one simple rule."""
    path = _write(
        tmp_path,
        f'[plugin]\nslug = "base"\nname = "x"\nkind = "{kind}"\napi_version = "1"\n'
        '[build]\ndockerfile = "Dockerfile"\n',
    )
    with pytest.raises(ManifestError, match="reserved"):
        load_manifest(path)


# ---------------------------------------------------------------------------
# base-image kind: [build].from / [build].context / [plugin].default.
# ---------------------------------------------------------------------------


_PIN = "debian:12-slim@sha256:" + "0" * 64

_MINIMAL_BASE = (
    '[plugin]\nslug = "deb"\nname = "deb (base)"\nkind = "base-image"\n'
    'api_version = "1"\n'
)


def _write_base_plugin(root: Path, body: str, slug: str = "deb") -> Path:
    """Lay out ``<root>/plugins/base-images/<slug>/manifest.toml``.

    ``root`` plays the checkout root: tests that exercise [build] path
    containment pass ``repo_root=root`` explicitly, exactly like the
    registry does for the real tree.
    """
    d = root / "plugins" / "base-images" / slug
    d.mkdir(parents=True)
    p = d / "manifest.toml"
    p.write_text(body)
    return p


def test_base_image_kind_accepted(tmp_path):
    """kind = "base-image" parses; from/context/default surface with
    their defaults."""
    path = _write_base_plugin(
        tmp_path,
        _MINIMAL_BASE + f'[build]\ndockerfile = "Dockerfile"\nfrom = "{_PIN}"\n',
    )
    m = load_manifest(path)
    assert m.kind == "base-image"
    assert m.from_ref == _PIN
    assert m.context == "."
    assert m.context_path == path.parent.resolve()
    assert m.is_default is False


def test_base_image_requires_from(tmp_path):
    """A base-image layer is a build-graph root: its upstream ref must
    come from data, not from an ARG default inside the Dockerfile."""
    path = _write_base_plugin(
        tmp_path, _MINIMAL_BASE + '[build]\ndockerfile = "Dockerfile"\n'
    )
    with pytest.raises(ManifestError, match=r"from is required for kind 'base-image'"):
        load_manifest(path)


def test_from_rejected_on_agent(tmp_path):
    """Non-root kinds get their parent from the build plan; a pinned
    upstream ref on an agent would be dead-but-plausible data."""
    path = _write(
        tmp_path,
        _MINIMAL_AGENT + f'[build]\ndockerfile = "Dockerfile"\nfrom = "{_PIN}"\n',
    )
    with pytest.raises(ManifestError, match="pin an upstream"):
        load_manifest(path)


def test_from_must_be_digest_pinned(tmp_path):
    """A floating tag makes the matrix irreproducible across a rebuild."""
    path = _write_base_plugin(
        tmp_path,
        _MINIMAL_BASE + '[build]\ndockerfile = "Dockerfile"\nfrom = "debian:12-slim"\n',
    )
    with pytest.raises(ManifestError, match="digest-pinned"):
        load_manifest(path)


@pytest.mark.parametrize(
    "bad",
    [
        "@sha256:",                                   # bare marker, no name/digest
        "garbage@sha256:zz",                          # digest is not hex
        f"@sha256:{'0' * 64}",                        # empty name:tag
        f"debian@sha256:{'0' * 64}",                  # no tag - the promise is name:tag
        f"debian:12-slim@sha256:{'0' * 63}",          # 63 hex chars
        f"debian:12-slim@sha256:{'0' * 65}",          # 65 hex chars
        f"debian:12-slim@sha256:{'A' * 64}",          # uppercase hex
        f"debian:12-slim@sha256:{'0' * 64} ",         # trailing junk
        f"x debian:12-slim@sha256:{'0' * 64}",        # leading junk
        f"debian:12-slim@sha512:{'0' * 64}",          # wrong algorithm
    ],
)
def test_from_pin_rejects_lookalikes(tmp_path, bad, request):
    """The old check was ``"@sha256:" in from_ref`` - a substring probe
    that accepted '@sha256:' itself and 'garbage@sha256:zz'. The pin
    must be the error message's promise, made executable: a non-empty
    name:tag followed by an anchored @sha256:<exactly 64 hex>."""
    slug = f"deb{request.node.callspec.indices['bad']}"
    path = _write_base_plugin(
        tmp_path,
        _MINIMAL_BASE.replace('slug = "deb"', f'slug = "{slug}"')
        + f'[build]\ndockerfile = "Dockerfile"\nfrom = "{bad}"\n',
        slug=slug,
    )
    with pytest.raises(ManifestError, match="digest-pinned"):
        load_manifest(path, repo_root=tmp_path)


@given(
    name=st.from_regex(r"[a-z0-9]{1,8}(/[a-z0-9]{1,8}){0,2}", fullmatch=True),
    tag=st.from_regex(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,16}", fullmatch=True),
    digest=st.text(alphabet="0123456789abcdef", min_size=64, max_size=64),
)
def test_from_pin_accepts_well_formed_refs(tmp_path_factory, name, tag, digest):
    """Property: every name:tag@sha256:<64 lowercase hex> loads, and the
    parsed from_ref round-trips verbatim."""
    tmp = tmp_path_factory.mktemp("pin")
    ref = f"{name}:{tag}@sha256:{digest}"
    path = _write_base_plugin(
        tmp,
        _MINIMAL_BASE + f'[build]\ndockerfile = "Dockerfile"\nfrom = "{ref}"\n',
    )
    assert load_manifest(path, repo_root=tmp).from_ref == ref


def test_context_upward_hop_inside_repo_accepted(tmp_path):
    """A shared sibling dir (no manifest.toml, invisible to discovery)
    is a legal build context."""
    shared = tmp_path / "plugins" / "base-images" / "_shared"
    shared.mkdir(parents=True)
    path = _write_base_plugin(
        tmp_path,
        _MINIMAL_BASE
        + f'[build]\ndockerfile = "Dockerfile"\nfrom = "{_PIN}"\n'
        'context = "../_shared"\n',
    )
    m = load_manifest(path, repo_root=tmp_path)
    assert m.context == "../_shared"
    assert m.context_path == shared.resolve()


def test_context_absolute_rejected(tmp_path):
    path = _write_base_plugin(
        tmp_path,
        _MINIMAL_BASE
        + f'[build]\ndockerfile = "Dockerfile"\nfrom = "{_PIN}"\n'
        'context = "/etc"\n',
    )
    with pytest.raises(ManifestError, match="must be relative, not absolute"):
        load_manifest(path)


def test_context_escaping_repo_rejected(tmp_path):
    """The manifest dir sits at <repo>/plugins/base-images/<slug>/, so
    four upward hops leave the repo checkout."""
    path = _write_base_plugin(
        tmp_path,
        _MINIMAL_BASE
        + f'[build]\ndockerfile = "Dockerfile"\nfrom = "{_PIN}"\n'
        'context = "../../../.."\n',
    )
    with pytest.raises(ManifestError, match="outside the allowed root"):
        load_manifest(path, repo_root=tmp_path)


def test_shared_dockerfile_upward_hop_accepted(tmp_path):
    """dockerfile may traverse into a shared sibling dir; the resolved
    path stays inside the repo checkout."""
    shared = tmp_path / "plugins" / "base-images" / "_shared"
    shared.mkdir(parents=True)
    (shared / "os-base.Dockerfile").write_text("ARG BASE_IMAGE\nFROM ${BASE_IMAGE}\n")
    path = _write_base_plugin(
        tmp_path,
        _MINIMAL_BASE
        + f'[build]\ndockerfile = "../_shared/os-base.Dockerfile"\nfrom = "{_PIN}"\n',
    )
    m = load_manifest(path, repo_root=tmp_path)
    assert m.dockerfile_path == (shared / "os-base.Dockerfile").resolve()
    assert m.dockerfile_path.is_file()


def test_dockerfile_absolute_rejected(tmp_path):
    path = _write_base_plugin(
        tmp_path,
        _MINIMAL_BASE + f'[build]\ndockerfile = "/etc/Dockerfile"\nfrom = "{_PIN}"\n',
    )
    with pytest.raises(ManifestError, match="must be relative, not absolute"):
        load_manifest(path)


def test_dockerfile_escaping_repo_rejected(tmp_path):
    path = _write_base_plugin(
        tmp_path,
        _MINIMAL_BASE
        + f'[build]\ndockerfile = "../../../../Dockerfile"\nfrom = "{_PIN}"\n',
    )
    with pytest.raises(ManifestError, match="outside the allowed root"):
        load_manifest(path, repo_root=tmp_path)


def test_shallow_manifest_cannot_escape_containment():
    """Depth-collapse probe: the old boundary was 'three .parent above
    the manifest dir', and ``.parent`` saturates at the filesystem
    root - a manifest only two directories deep (e.g. /tmp/x/) got
    root '/', i.e. no boundary at all, and could read /etc/passwd.
    Containment must not depend on how deep the manifest happens to
    sit."""
    import shutil
    import tempfile

    # Deliberately shallow: /tmp/<x>/manifest.toml is 2 levels below /.
    d = Path(tempfile.mkdtemp(dir="/tmp"))
    try:
        p = d / "manifest.toml"
        p.write_text(
            _MINIMAL_BASE
            + f'[build]\ndockerfile = "{"../" * 12}etc/passwd"\nfrom = "{_PIN}"\n'
        )
        with pytest.raises(ManifestError, match="outside the allowed root"):
            load_manifest(p)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_containment_is_position_independent(tmp_path):
    """The same manifest content must get the same verdict at any
    depth: the boundary is the explicitly supplied checkout root (or,
    without one, the manifest's own directory) - never a count of
    parent directories."""
    body = (
        _MINIMAL_BASE
        + f'[build]\ndockerfile = "../_shared/os-base.Dockerfile"\nfrom = "{_PIN}"\n'
    )
    # Canonical depth, boundary supplied: the upward hop is legal.
    shared = tmp_path / "canon" / "plugins" / "base-images" / "_shared"
    shared.mkdir(parents=True)
    (shared / "os-base.Dockerfile").write_text("ARG BASE_IMAGE\n")
    canon = _write_base_plugin(tmp_path / "canon", body)
    m = load_manifest(canon, repo_root=tmp_path / "canon")
    assert m.dockerfile_path == (shared / "os-base.Dockerfile").resolve()

    # Depth 0 under tmp, no boundary supplied: the hop fails closed
    # instead of being judged against an accidental ancestor.
    solo = tmp_path / "solo"
    solo.mkdir()
    (solo / "manifest.toml").write_text(body)
    with pytest.raises(ManifestError, match="outside the allowed root"):
        load_manifest(solo / "manifest.toml")


def test_default_true_on_official_accepted(tmp_path):
    path = _write_base_plugin(
        tmp_path,
        _MINIMAL_BASE
        + 'default = true\n'
        + f'[build]\ndockerfile = "Dockerfile"\nfrom = "{_PIN}"\n',
    )
    m = load_manifest(path)
    assert m.is_default is True
    assert m.tier == "official"


def test_default_wrong_type_rejected(tmp_path):
    path = _write_base_plugin(
        tmp_path,
        _MINIMAL_BASE
        + 'default = "yes"\n'
        + f'[build]\ndockerfile = "Dockerfile"\nfrom = "{_PIN}"\n',
    )
    with pytest.raises(ManifestError, match="expected bool"):
        load_manifest(path)


def test_default_on_community_rejected(tmp_path):
    """A community/deprecated default would silently empty the official
    matrix for its dimension (tag_tier takes the most restrictive tier)."""
    path = _write_base_plugin(
        tmp_path,
        _MINIMAL_BASE
        + 'tier = "community"\ndefault = true\n'
        + f'[build]\ndockerfile = "Dockerfile"\nfrom = "{_PIN}"\n',
    )
    with pytest.raises(ManifestError, match='must be tier = "official"'):
        load_manifest(path)
