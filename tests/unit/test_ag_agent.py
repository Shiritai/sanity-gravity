"""Unit tests for the ``ag`` (Antigravity IDE) agent plugin.

``ag`` is the plugin the repo is named after, and until now the only one
with no unit test: its contract lived entirely in integration tests that
need a built image. That gap is what let the install method rot
unnoticed. The apt repo ``ag`` installed from froze in April 2026, so
every image built after that shipped Antigravity 1.107.0, whose bundled
language-server certificate expired on 2026-09-04 - and the Agent
Manager stopped answering with no error a user could act on (#42).

Two halves, both cheap enough to run without Docker:

* the manifest half, in the shape of ``test_ocd_agent.py`` - identity,
  ``requires = ["display"]``, tier, capability solving;
* the install half - the tarball pin, the certificate gate, and the
  absence of the apt/dpkg-divert machinery the 1.x install needed. The
  pin is read out of the Dockerfile rather than restated here, so a bump
  is one edit; what is asserted is that the pin has a shape upstream
  cannot silently re-point, and that the docs name the same version.
"""
from __future__ import annotations

import re

import pytest

from sanity_gravity.domain.capability import CapabilityConflictError, solve
from sanity_gravity.domain.tags import Tag
from sanity_gravity.plugins.registry import (
    PluginRegistry,
    default_registry,
    reset_default_registry,
)
from tests.support import REPO_ROOT, dockerfile_lines

_PLUGINS_DIR = REPO_ROOT / "plugins"
_AG_DIR = _PLUGINS_DIR / "agents" / "ag"
_DOCKERFILE = _AG_DIR / "Dockerfile"
_GRAVITY_CLI = _AG_DIR / "rootfs" / "usr" / "local" / "bin" / "gravity-cli"
_TAGS_DOC = REPO_ROOT / "docs" / "tags.md"

#: Spot-check literal, deliberately not the full ag-* list: one desktop
#: kind each, so a derivation that stopped checking anything still has
#: to get these three right.
AG_KNOWN_TAGS = [
    Tag("ag", "xfce", "kasm"),
    Tag("ag", "lxqt", "vnc"),
    Tag("ag", "openbox", "ssh"),
]

#: The immutable half of the download URL. ``<version>-<build id>`` names
#: one build for good: the objects carry ``x-goog-metageneration: 1``,
#: every build gets a fresh id, and no floating "latest" path exists. A
#: pin is only a pin while the URL it points at cannot be re-aimed.
IMMUTABLE_URL_PATH = "release2/j0qc3/antigravity/stable"

#: Where the sha256 is cross-checked against upstream rather than only
#: against ourselves: Google publishes it per platform.
UPDATER_API_HOST = "antigravity-ide-auto-updater-974169037036.us-central1.run.app"

#: 14 days. The certificate the extension pins as its only CA is the
#: single point of failure #42 is about, so the build has to go red while
#: there is still time to re-pin - not on the morning it expires.
CERT_GRACE_SECONDS = "1209600"


@pytest.fixture(scope="module")
def reg() -> PluginRegistry:
    """Cold-load the builtin registry from the on-disk plugin tree."""
    reset_default_registry()
    return default_registry(_PLUGINS_DIR)


@pytest.fixture(scope="module")
def dockerfile() -> str:
    """The ag Dockerfile with comments stripped.

    Comments are removed on purpose: a build step that survives only in
    prose does not run, and a repo-wide guard that counts a comment as
    coverage is the failure mode the whole meta layer exists to avoid.
    """
    return "\n".join(dockerfile_lines(_DOCKERFILE))


@pytest.fixture(scope="module")
def gravity_cli() -> str:
    return _GRAVITY_CLI.read_text(encoding="utf-8")


def _args(dockerfile: str) -> dict[str, str]:
    """``ARG NAME=value`` defaults, as a mapping."""
    return dict(
        re.findall(r"^ARG\s+([A-Z0-9_]+)=(\S+)\s*$", dockerfile, re.MULTILINE)
    )


# -- discovery and manifest ---------------------------------------------


def test_ag_is_discovered(reg):
    assert "ag" in reg.agents


def test_ag_manifest_identity(reg):
    m = reg.agents["ag"]
    assert m.slug == "ag"
    assert m.name == "antigravity"
    assert m.kind == "agent"
    assert m.api_version == "1"


def test_ag_is_a_gui_agent_that_provides_the_ide_capability(reg):
    """``provides = ["ide"]`` is what routes the ``ide`` verb here, and
    ``requires = ["display"]`` is why no ag-none-* tag exists."""
    m = reg.agents["ag"]
    assert m.provides == ("ide",)
    assert m.requires == ("display",)


def test_ag_injects_no_host_env(reg):
    """Sign-in happens inside the container, so no host secret is
    forwarded - same rule as every other agent."""
    assert reg.agents["ag"].environment == ()


def test_ag_is_official(reg):
    assert reg.agents["ag"].tier == "official"


def test_ag_declares_the_ide_maintenance_contract(reg):
    """The ``ide`` verb reads this instead of knowing about ag: the
    injected files are what makes ``ide update`` work on a container
    built before the current checkout."""
    ide = reg.agents["ag"].ide
    assert ide is not None
    assert ide.command == ("/usr/local/bin/gravity-cli", "ide")
    assert "usr/local/bin/gravity-cli" in ide.inject
    for rel in ide.inject:
        assert (_AG_DIR / "rootfs" / rel).is_file(), (
            f"[ide] inject names {rel}, which is not in the plugin rootfs"
        )


# -- capability solving -------------------------------------------------


@pytest.mark.parametrize("tag", AG_KNOWN_TAGS, ids=lambda t: str(t))
def test_ag_known_tags_pass(tag, reg):
    assert solve(tag, reg) == tag


@pytest.mark.parametrize("connector", ["ssh", "kasm", "vnc"])
def test_ag_headless_tags_fail(connector, reg):
    """The IDE is an Electron app: it cannot run on the ``none``
    desktop, whichever connector is asked for."""
    with pytest.raises(CapabilityConflictError) as excinfo:
        solve(Tag("ag", "none", connector), reg)
    assert excinfo.value.missing == frozenset({"display"})


# -- the tarball pin ----------------------------------------------------


def test_the_ide_is_pinned_by_version_and_build_id(dockerfile):
    """Two values, not one. The version alone does not name a build:
    the build id is minted per build and cannot be derived from the
    version, so both have to be written down at pin time."""
    args = _args(dockerfile)
    version = args.get("ANTIGRAVITY_IDE_VERSION", "")
    build = args.get("ANTIGRAVITY_IDE_BUILD", "")
    assert re.fullmatch(r"2\.\d+\.\d+", version), (
        f"ANTIGRAVITY_IDE_VERSION={version!r}: the standalone IDE line is "
        "2.x; 1.x is the deprecated apt package this layer moved off (#42)"
    )
    assert re.fullmatch(r"\d{10,}", build), (
        f"ANTIGRAVITY_IDE_BUILD={build!r} is not a build id"
    )


def test_both_architectures_carry_their_own_sha256(dockerfile):
    """One sum per architecture, and they must differ: a single sum
    shared by both branches means one of them was copied, and the
    tarballs are not the same file."""
    sums = re.findall(r"\b[0-9a-f]{64}\b", dockerfile)
    assert len(sums) == 2, (
        f"expected one 64-hex sha256 per architecture, found {len(sums)}: "
        f"{sums}"
    )
    assert len(set(sums)) == 2, "amd64 and arm64 share a sha256 sum"
    for arch in ("amd64", "arm64"):
        assert re.search(rf"\b{arch}\)", dockerfile), (
            f"no {arch} branch in the architecture case"
        )


def test_the_download_is_verified_before_it_is_used(gravity_cli, dockerfile):
    """``sha256sum -c`` is the whole point of the pin. Its absence turns
    a pinned URL back into "whatever the network handed us"."""
    assert "sha256sum -c" in gravity_cli
    assert IMMUTABLE_URL_PATH in gravity_cli, (
        "the download URL no longer spells the immutable "
        f"{IMMUTABLE_URL_PATH} path"
    )
    assert "%20" in gravity_cli, (
        "the artifact is named 'Antigravity IDE.tar.gz' - the space has to "
        "be encoded or curl gets two arguments"
    )
    assert UPDATER_API_HOST in gravity_cli, (
        "nothing cross-checks the pin against the sha256 Google publishes"
    )
    # The Dockerfile hands its pin to the same installer, so there is one
    # download path rather than one per entry point.
    assert "gravity-cli ide install" in dockerfile


def test_the_pinned_version_is_the_one_the_docs_name(dockerfile):
    """A pin nobody can read is a pin nobody re-checks. The version in
    docs/tags.md is what a user compares against upstream's releases
    page, so it moves with the ARG or this goes red."""
    version = _args(dockerfile)["ANTIGRAVITY_IDE_VERSION"]
    assert version in _TAGS_DOC.read_text(encoding="utf-8"), (
        f"docs/tags.md does not name the pinned IDE version {version}"
    )


def test_the_app_directory_is_spelled_once(dockerfile, gravity_cli):
    """The Dockerfile's certificate gate and the installer both address
    the install directory; two spellings is one rename away from a gate
    that checks a path nothing installs to."""
    app_dir = _args(dockerfile)["ANTIGRAVITY_DIR"]
    assert re.search(rf"^AG_DIR={re.escape(app_dir)}$", gravity_cli, re.MULTILINE), (
        f"the Dockerfile installs to {app_dir} but gravity-cli's AG_DIR "
        "names something else"
    )


# -- the certificate gate ----------------------------------------------


def test_the_build_fails_on_a_certificate_about_to_expire(dockerfile):
    """The reason this whole migration exists. The IDE hands the bundled
    cert.pem to its own language-server connection as the only CA, so an
    expired one fails every agent call in the TLS handshake and the Agent
    Manager goes silent. A build must not be able to ship that."""
    assert "openssl x509" in dockerfile and "-checkend" in dockerfile, (
        "no build-time certificate check: an expired bundled certificate "
        "would ship a dead Agent Manager again (#42)"
    )
    assert f"-checkend {CERT_GRACE_SECONDS}" in dockerfile, (
        f"the certificate check must use a {CERT_GRACE_SECONDS}s (14 day) "
        "grace window, so the build goes red while re-pinning is still "
        "possible"
    )
    assert "languageServer/cert.pem" in dockerfile, (
        "the check no longer names the certificate the extension pins"
    )
    assert "#42" in dockerfile, (
        "the failure message must point at the issue that explains it; a "
        "bare 'certificate expired' sends the reader nowhere"
    )
    assert "exit 1" in dockerfile, "the certificate check does not fail the build"


# -- what the 1.x install left behind ----------------------------------


@pytest.mark.parametrize(
    "token, why",
    [
        ("apt.pkg.dev", "the 1.x apt repo, frozen since 2026-04-16"),
        ("antigravity-debian", "the frozen apt suite"),
        ("sources.list.d/antigravity", "the apt source file"),
        ("apt/keyrings", "the repo signing key"),
        ("--only-upgrade", "apt-driven IDE upgrades"),
        ("dpkg-divert", "protection against an apt upgrade that cannot happen"),
        ("/usr/share/doc", "the doc/man purge"),
        ("--disable-zygote", "a switch Chromium never defined"),
    ],
)
def test_the_plugin_carries_no_trace_of_the_apt_install(token, why, dockerfile, gravity_cli):
    """Each token belongs to the install this change replaced.

    ``dpkg-divert`` had one job: keep ``apt upgrade`` from overwriting
    the wrapper. A tarball is not a package, so nothing can overwrite it
    and the protection guards a threat that no longer exists. The doc
    purge is compliance debt (it deletes the licence files the shipped
    software's own terms require), and ``--disable-zygote`` was a typo
    for ``--no-zygote`` that Chromium silently ignored for as long as it
    was there.
    """
    for name, text in (("Dockerfile", dockerfile), ("gravity-cli", gravity_cli)):
        assert token not in text, f"{name} still carries {token} ({why})"


def test_the_wrapper_keeps_the_flags_the_container_needs(gravity_cli):
    """The three that are load-bearing under Xvnc, plus the corrected
    zygote switch. ``--no-sandbox`` because the container grants no user
    namespaces, ``--disable-dev-shm-usage`` because /dev/shm is small,
    ``--disable-namespace-sandbox`` for the same reason as the first."""
    for flag in (
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--no-zygote",
        "--disable-namespace-sandbox",
    ):
        assert flag in gravity_cli, f"the wrapper no longer passes {flag}"


def test_the_updater_is_cut_off_at_the_root(gravity_cli):
    """Upstream's own releases page says these builds auto-update by
    default, and the update that fires is the one that moves users onto
    the separate 2.0 app. VS Code's update service reports
    MissingConfiguration and stays off when product.json names no URL -
    a switch the sandbox user cannot flip back."""
    assert "del(.updateUrl" in gravity_cli, (
        "product.json keeps its update URL: the IDE can replace itself "
        "inside the sandbox"
    )


# -- sign-in: the deep link ---------------------------------------------


def test_the_url_scheme_handler_is_registered(gravity_cli):
    """2.x sign-in does not come back on a localhost port any more.
    antigravity.google/auth-success hands the browser an
    ``antigravity-ide://oauth-success`` link, so without a handler the
    last step of the login lands nowhere - and the symptom is a login
    that simply never completes."""
    assert "x-scheme-handler/antigravity-ide" in gravity_cli
    assert "--open-url" in gravity_cli, (
        "the handler entry must exec the IDE with --open-url %U"
    )
    assert "NoDisplay=true" in gravity_cli, (
        "the handler is a handler, not a second menu entry"
    )
    assert "mimeapps.list" in gravity_cli, (
        "nothing makes our handler the default for the scheme, so xdg-open "
        "can still resolve it to nothing"
    )


def test_the_menu_entry_declares_the_window_class(gravity_cli):
    """The tarball ships no .desktop, so ours is the only one. The WM
    class is what the openbox/shutdown side identifies the window by."""
    assert "StartupWMClass=antigravity-ide" in gravity_cli


def test_the_desktop_entries_exec_the_wrapper_not_the_path_command(gravity_cli):
    """Where the sandbox flags come from. ``/usr/bin/antigravity-ide`` is
    upstream's CLI shim: it re-spawns the app itself, from the vendor
    binary, so a menu entry pointing at it would start the IDE with none
    of the flags the container needs. The 1.x deb's own entries named the
    app directory for the same reason, which is why that install worked
    while the sed meant to patch ``Exec=/usr/bin/...`` matched nothing."""
    for line in ("Exec=$AG_WRAPPER %F", "Exec=$AG_WRAPPER --open-url %U"):
        assert line in gravity_cli, f"a .desktop entry no longer has {line}"
