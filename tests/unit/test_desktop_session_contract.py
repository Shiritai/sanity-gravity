"""The desktop-session contract: a display plugin ships its launcher.

The VNC-family connectors start a graphical session by exec'ing
``/usr/local/bin/desktop-session``, with ``startxfce4`` only as the
fallback for images that predate the contract. That indirection is what
lets a new desktop plugin land without touching a connector - and it is
also what makes a forgotten launcher invisible: the connector falls
through to ``startxfce4``, which a non-xfce desktop does not have, so the
tag builds green and the session dies at container start, in a log nobody
reads until someone opens the browser.

The producer side is therefore checked here, where a plugin's manifest
and its build instructions can be read together, rather than left to
review. Structural, not behavioural: the image is not built, so this says
the launcher is shipped, not that the desktop it starts works.
"""
from __future__ import annotations

import re
from pathlib import Path

from sanity_gravity.plugins.manifest import PluginManifest, load_manifest
from tests.support import REPO_ROOT, dockerfile_lines

#: The single path both connectors exec. Spelled once, here.
LAUNCHER = "/usr/local/bin/desktop-session"

#: The capability that makes a plugin a desktop to the connectors.
DISPLAY = "display"

_PLUGINS_DIR = REPO_ROOT / "plugins"


def _manifests() -> list[PluginManifest]:
    """Every plugin, read straight off disk.

    Deliberately not the registry: the question is about manifest text
    and sibling files, and a cached global registry would answer it for
    whichever plugin root some earlier test happened to load.
    """
    return [load_manifest(p) for p in sorted(_PLUGINS_DIR.glob("*/*/manifest.toml"))]


#: A command handing the launcher to ``rm``/``unlink`` instead of writing
#: it. Bounded by the shell separators so a purge elsewhere in the same
#: ``RUN`` does not match.
_REMOVAL = re.compile(r"\b(?:rm|unlink)\b[^;&|]*" + re.escape(LAUNCHER))


def _writes_launcher(dockerfile: Path) -> bool:
    """Whether the build leaves the launcher behind.

    Naming the path is not enough: ``rm -f <path>`` names it too, so a
    removal cancels the writes before it.
    """
    written = False
    for line in dockerfile_lines(dockerfile):
        if LAUNCHER not in line:
            continue
        if _REMOVAL.search(line):
            return False
        written = True
    return written


def _ships_launcher(m: PluginManifest) -> bool:
    """Either form counts: a rootfs file copied in, or a build step that
    writes the path."""
    staged = m.dir / "rootfs" / LAUNCHER.lstrip("/")
    # The connectors run the launcher behind `[ -x ]`, so a staged file
    # without the executable bit falls back to startxfce4 in silence.
    # Read off the mode git records rather than os.access, which answers
    # for whoever happens to run the suite.
    if staged.is_file() and staged.stat().st_mode & 0o111:
        return True
    return _writes_launcher(m.dockerfile_path)


def test_display_plugins_ship_the_session_launcher():
    providers = [m for m in _manifests() if DISPLAY in m.provides]
    assert providers, (
        f"no plugin provides '{DISPLAY}': the capability was renamed or the "
        "plugin tree moved, and this guard is now watching nothing"
    )
    missing = sorted(m.slug for m in providers if not _ships_launcher(m))
    assert not missing, (
        f"these plugins provide '{DISPLAY}' but ship no {LAUNCHER}: "
        f"{missing}. Every kasm/vnc tag built on them execs that path and "
        "falls back to startxfce4, which they do not have. Write it from the "
        f"plugin's Dockerfile, or stage it at rootfs{LAUNCHER} with the "
        "executable bit set."
    )


def test_headless_desktop_is_out_of_scope():
    """The contract binds display providers only. `none` starts no
    session, and widening the guard past the capability would demand a
    launcher from every connector and agent as well."""
    providers = {m.slug for m in _manifests() if DISPLAY in m.provides}
    assert "xfce" in providers
    assert "none" not in providers
# ---------------------------------------------------------------------------
# What counts as shipping. Three shapes passed the first version of this
# guard while the image would still have started no session: a mention in
# a trailing comment, a staged file the connector's ``[ -x ]`` test would
# reject, and a line that deletes the launcher.
# ---------------------------------------------------------------------------


def _display_plugin(tmp_path, dockerfile: str, staged: int | None = None):
    """A throwaway display plugin, so the shapes can be tested directly."""
    (tmp_path / "manifest.toml").write_text(
        '[plugin]\nslug = "probe"\nname = "probe"\n'
        'kind = "desktop"\napi_version = "1"\n'
        f'[capabilities]\nprovides = ["{DISPLAY}"]\nrequires = []\n'
        '[build]\ndockerfile = "Dockerfile"\n',
        encoding="utf-8",
    )
    (tmp_path / "Dockerfile").write_text(dockerfile, encoding="utf-8")
    if staged is not None:
        launcher = tmp_path / "rootfs" / LAUNCHER.lstrip("/")
        launcher.parent.mkdir(parents=True, exist_ok=True)
        launcher.write_text("#!/bin/sh\nexec true\n", encoding="utf-8")
        launcher.chmod(staged)
    return load_manifest(tmp_path / "manifest.toml")


def test_a_trailing_comment_does_not_ship_the_launcher(tmp_path):
    m = _display_plugin(tmp_path, f"FROM scratch\nRUN true  # TODO: ship {LAUNCHER}\n")
    assert not _ships_launcher(m)


def test_a_staged_launcher_without_the_executable_bit_does_not_count(tmp_path):
    """The connectors gate on ``[ -x ]``, so a 0644 file is the silent
    fallback to startxfce4 this guard exists to catch."""
    m = _display_plugin(tmp_path, "FROM scratch\n", staged=0o644)
    assert not _ships_launcher(m)


def test_deleting_the_launcher_does_not_count_as_shipping(tmp_path):
    m = _display_plugin(tmp_path, f"FROM scratch\nRUN rm -f {LAUNCHER}\n")
    assert not _ships_launcher(m)


def test_a_staged_executable_launcher_counts(tmp_path):
    m = _display_plugin(tmp_path, "FROM scratch\n", staged=0o755)
    assert _ships_launcher(m)


def test_a_build_step_writing_the_launcher_counts(tmp_path):
    m = _display_plugin(
        tmp_path,
        "FROM scratch\n"
        f"RUN printf '%s\\n' '#!/bin/sh' 'exec true' > {LAUNCHER} \\\n"
        f"    && chmod +x {LAUNCHER}\n",
    )
    assert _ships_launcher(m)
