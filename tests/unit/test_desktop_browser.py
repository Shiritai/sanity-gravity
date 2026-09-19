"""The bundled browser: whoever draws the desktop installs it.

A desktop with no browser is a desktop that cannot open a link - an
agent's own web UI on loopback, the IDE's docs, an OAuth page. The
install used to sit in the ``ag`` agent layer, so the browser followed
the agent instead of the display: ``ag-xfce-kasm`` had one and
``cc-xfce-kasm`` did not, though both draw the same desktop.

It now follows the capability. Every plugin that provides ``display``
runs one installer the base image stages, and the headless ``none``
layer runs nothing. A Dockerfile has no include, so "one recipe" holds
only while the checks below do: the staged script is the single copy,
the desktop layers invoke it identically, and no plugin grows its own.

Structural, not behavioural: no image is built here, so this says the
recipe is invoked, not that Chrome starts. That half is
``tests/integration/test_desktop_browser.py``.
"""
from __future__ import annotations

import pytest

from sanity_gravity.plugins.manifest import PluginManifest
from sanity_gravity.plugins.registry import (
    PluginRegistry,
    default_registry,
    reset_default_registry,
)
from tests.support import REPO_ROOT, dockerfile_lines

_PLUGINS_DIR = REPO_ROOT / "plugins"
_BASE_DOCKERFILE = REPO_ROOT / "sandbox" / "Dockerfile.base"

#: The one recipe, staged in the base image's rootfs and run from there.
#: Spelled once, here; the desktop Dockerfiles spell it once each.
INSTALLER = "/usr/local/lib/sanity-gravity/install-browser.sh"

#: Where that path comes from: the base layer's ``COPY rootfs /``. It is
#: the only channel a plugin layer has to shared files - a plugin builds
#: with its own directory as the build context, so it can COPY nothing
#: from the repo but its own tree.
STAGED = REPO_ROOT / "sandbox" / "rootfs" / INSTALLER.lstrip("/")

#: The capability that makes a plugin a desktop.
DISPLAY = "display"

#: Text no Dockerfile has a reason to contain once the recipe moved:
#: each token is a step of the install (Google's apt repo and its signing
#: key on amd64, the chromium PPA on arm64) or of the wrapper it plants.
#: A second copy of the recipe is what this change exists to remove, and
#: a copy that drifts is worse than the duplication was.
RECIPE_TOKENS = (
    "dl.google.com",
    "linux_signing_key.pub",
    "ppa:xtradeb/apps",
    "google-chrome-stable",
    "google-chrome-safe",
    "x-www-browser",
)


@pytest.fixture(scope="module")
def reg() -> PluginRegistry:
    """Cold-load the builtin registry from the on-disk plugin tree."""
    reset_default_registry()
    return default_registry(_PLUGINS_DIR)


def _invocations(m: PluginManifest) -> list[str]:
    """The plugin's build steps that run the installer, as written.

    Comments are already gone (``dockerfile_lines``), so a plugin that
    only mentions the path in prose invokes nothing - which is the shape
    a half-finished port leaves behind.
    """
    return [
        line.strip() for line in dockerfile_lines(m.dockerfile_path)
        if INSTALLER in line
    ]


def _instruction_kinds(dockerfile) -> list[str]:
    """``["ARG", "FROM", ...]`` for one Dockerfile, continuations joined."""
    kinds: list[str] = []
    continued = False
    for line in dockerfile_lines(dockerfile):
        stripped = line.strip()
        if not stripped:
            continue
        if not continued:
            kinds.append(stripped.split()[0])
        continued = stripped.endswith("\\")
    return kinds


def test_the_browser_follows_the_display_capability(reg):
    """The whole point of the move: the set of plugins that install a
    browser is exactly the set that draws a desktop. Read over every
    plugin, not the desktops alone, so an agent quietly taking the
    install back also fails here."""
    providers = {m.slug for m in reg.all_manifests() if DISPLAY in m.provides}
    assert providers, (
        f"no plugin provides {DISPLAY!r}: the capability was renamed or the "
        "plugin tree moved, and this guard is now watching nothing"
    )
    installers = {m.slug for m in reg.all_manifests() if _invocations(m)}
    assert installers == providers, (
        f"plugins providing {DISPLAY!r}: {sorted(providers)}; plugins "
        f"running {INSTALLER}: {sorted(installers)}. A desktop missing from "
        "the second set builds a session that cannot open a link; a plugin "
        "in it that provides no display installs a browser nothing can draw."
    )


def test_every_desktop_invokes_the_installer_identically(reg):
    """One recipe means one invocation. Three spellings of the same call
    are three places a flag, a path or a guard can drift apart, which is
    the duplication this change removed rewritten in a smaller font."""
    calls = {
        m.slug: _invocations(m)
        for m in reg.desktops.values() if DISPLAY in m.provides
    }
    twice = {slug: lines for slug, lines in calls.items() if len(lines) != 1}
    assert not twice, (
        f"each desktop runs {INSTALLER} exactly once; these do not: {twice}"
    )
    spellings = {lines[0] for lines in calls.values()}
    assert len(spellings) == 1, (
        f"the desktops invoke the installer differently: {sorted(spellings)}"
    )


def test_the_headless_desktop_installs_nothing(reg):
    """``none`` has no display to draw a browser on, and the promise that
    it stays a pure ENV layer is what keeps the headless tags the small
    images they are advertised as."""
    none = reg.desktops["none"]
    assert DISPLAY not in none.provides
    assert _instruction_kinds(none.dockerfile_path) == ["ARG", "FROM", "ENV"], (
        "the headless desktop layer grew build instructions: "
        f"{_instruction_kinds(none.dockerfile_path)}"
    )


def test_no_plugin_carries_its_own_browser_recipe(reg):
    """The recipe lives in one file. A plugin re-deriving it - the way
    ``ag`` carried it before, and a second agent could copy tomorrow -
    gives the tree two browsers to keep in step and only one of them
    ever gets the fix."""
    offenders: dict[str, list[str]] = {}
    for m in reg.all_manifests():
        text = "\n".join(dockerfile_lines(m.dockerfile_path))
        hits = [tok for tok in RECIPE_TOKENS if tok in text]
        if hits:
            offenders[m.slug] = hits
    assert not offenders, (
        f"these plugins spell out browser-install steps: {offenders}. The "
        f"recipe belongs in {INSTALLER}; run it instead of repeating it."
    )


def test_the_base_layer_stages_the_installer_without_running_it():
    """The base image carries the script so every desktop can reach it,
    and runs it nowhere: a browser in the base would land in the headless
    tags too, which is the outcome this split exists to avoid."""
    base = "\n".join(dockerfile_lines(_BASE_DOCKERFILE))
    assert INSTALLER not in base, (
        f"{_BASE_DOCKERFILE.name} runs {INSTALLER}: every tag, headless "
        "ones included, would then ship a browser"
    )
    assert not [tok for tok in RECIPE_TOKENS if tok in base]


def test_the_staged_installer_is_executable():
    """``RUN <path>`` needs the executable bit, and the bit is carried
    by the checkout the image is built from - a 0644 file in the tree
    is a build failure on every desktop layer at once. Read the file's
    mode rather than os.access, which answers for whoever happens to
    run the suite."""
    assert STAGED.is_file(), (
        f"{STAGED.relative_to(REPO_ROOT)} is missing, so the base image "
        f"stages no {INSTALLER} for the desktop layers to run"
    )
    assert STAGED.stat().st_mode & 0o111, (
        f"{STAGED.relative_to(REPO_ROOT)} is not executable; the desktop "
        "layers run it directly"
    )


def _arch_branches() -> tuple[str, str]:
    """The installer's two halves: amd64, then everything else.

    The split is a plain ``if`` on ``dpkg --print-architecture``, so it
    can be read as text. If that ever stops being true the tests below
    say so here, once, instead of each passing vacuously.
    """
    script = STAGED.read_text(encoding="utf-8")
    _, marker, rest = script.partition('"$arch" = "amd64"')
    assert marker, "the installer no longer branches on the architecture"
    amd64, sep, other = rest.partition("\nelse\n")
    assert sep, "the installer's architecture test has no second branch"
    return amd64, other


def test_the_installer_covers_both_architectures():
    """amd64 gets Chrome from Google's repo; arm64 (Apple Silicon) has no
    Chrome build at all, so it gets chromium from the PPA."""
    amd64, other = _arch_branches()
    assert "dl.google.com" in amd64 and "google-chrome-stable" in amd64
    assert "ppa:xtradeb/apps" in other and "chromium" in other


def test_both_architectures_install_xdg_utils():
    """``xdg-open`` is what a link is handed to - by the desktop's file
    manager, by an agent, by ``dsh web``. Chrome's deb depends on
    xdg-utils and the chromium route does not, so the dependency is
    spelled out on both branches rather than inherited on one."""
    amd64, other = _arch_branches()
    assert "xdg-utils" in amd64, "the amd64 branch installs no xdg-utils"
    assert "xdg-utils" in other, "the arm64 branch installs no xdg-utils"


def test_the_installer_makes_the_browser_the_system_default():
    """What turns an installed binary into *the* browser: the sandbox
    wrapper, the names callers spell, and the link groups the xdg-open
    chain ends at. Without them a click on a link reaches nothing,
    whichever desktop drew it."""
    script = STAGED.read_text(encoding="utf-8")
    assert "--no-sandbox" in script, (
        "the wrapper drops --no-sandbox: the browser's own sandbox needs "
        "privileges the container does not grant, so it would not start"
    )
    for link in ("/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"):
        assert f"ln -sf /usr/bin/google-chrome-safe {link}" in script, (
            f"{link} no longer points at the wrapper"
        )


def test_the_link_groups_are_left_to_update_alternatives():
    """x-www-browser belongs to an alternatives link group that both
    browser packages register - chrome's deb for google-chrome-stable,
    chromium's for /usr/bin/chromium. A plain symlink over the top leaves
    the database naming the bare binary, so the next --auto pass restores
    it and drops --no-sandbox with it. The wrapper has to be registered
    and pinned, not linked."""
    script = STAGED.read_text(encoding="utf-8")
    assert "ln -sf /usr/bin/google-chrome-safe /usr/bin/x-www-browser" not in script, (
        "the installer overwrites the alternatives link by hand again"
    )
    assert "update-alternatives --install" in script
    assert "update-alternatives --set" in script
    for group in ("x-www-browser", "gnome-www-browser"):
        assert group in script, f"{group} is no longer pointed at the wrapper"


def test_the_menu_entry_is_resolved_by_glob_and_fails_closed():
    """The entry's file name belongs to the package: google-chrome.desktop
    on amd64, chromium.desktop from the PPA on arm64. A hard-coded list
    silently patches nothing when a package renames its entry - the arm64
    half of this change was exactly that kind of blind spot - so the
    installer globs both families and treats an empty match as a build
    failure."""
    script = STAGED.read_text(encoding="utf-8")
    for glob in ("google-chrome*.desktop", "chromium*.desktop"):
        assert glob in script, f"the menu-entry patch no longer globs {glob}"
    assert 'if [ "$patched" -eq 0 ]' in script and "exit 1" in script, (
        "a build that patched no menu entry must fail, not ship an entry "
        "that starts the browser without the wrapper"
    )


def test_a_mentioned_installer_is_not_an_invoked_one(tmp_path):
    """What counts as running it. A path named in a comment is the shape
    of a port someone wrote down and did not finish, and it must not read
    as coverage."""
    (tmp_path / "manifest.toml").write_text(
        '[plugin]\nslug = "probe"\nname = "probe"\n'
        'kind = "desktop"\napi_version = "1"\n'
        f'[capabilities]\nprovides = ["{DISPLAY}"]\nrequires = []\n'
        '[build]\ndockerfile = "Dockerfile"\n',
        encoding="utf-8",
    )
    (tmp_path / "Dockerfile").write_text(
        f"FROM scratch\nRUN true  # TODO: run {INSTALLER}\n", encoding="utf-8",
    )
    from sanity_gravity.plugins.manifest import load_manifest

    assert not _invocations(load_manifest(tmp_path / "manifest.toml"))
