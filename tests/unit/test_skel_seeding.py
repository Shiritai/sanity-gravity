"""Guards for the skel .zshrc the sandbox seeds into every user home.

The file is image contract rather than user config: it is baked in by
``COPY rootfs /`` and copied into homes ``useradd -m`` never touches.
Nothing in it is reachable from Python, so what is pinned here is what
the source must keep saying; the runtime proof lives in the container.
"""
from __future__ import annotations

import re

from tests.support import REPO_ROOT

_SKEL_ZSHRC = REPO_ROOT / "sandbox" / "rootfs" / "etc" / "skel" / ".zshrc"
_DOCKERFILE_BASE = REPO_ROOT / "sandbox" / "Dockerfile.base"

#: Editor packages against the commands each one actually registers on
#: Debian/Ubuntu. ``vim-tiny`` is why the table exists: it installs
#: ``/usr/bin/vim.tiny`` plus the ``vi``/``view``/``ex``/``editor``
#: alternatives, and never a ``vim``.
_EDITOR_COMMANDS = {
    "vim-tiny": frozenset({"vi", "view", "ex", "editor", "vim.tiny"}),
    "vim": frozenset({"vim", "vi", "view", "ex", "editor"}),
    "nano": frozenset({"nano", "editor"}),
    "emacs": frozenset({"emacs", "editor"}),
}

#: One package per line inside the apt-get install continuation.
_APT_LINE = re.compile(r"^\s+([a-z0-9][a-z0-9.+-]*)\s+\\$")


def _apt_packages() -> set[str]:
    """Every package Dockerfile.base installs."""
    return {
        m.group(1)
        for m in map(_APT_LINE.match, _DOCKERFILE_BASE.read_text().splitlines())
        if m
    }


def _skel_editor() -> str:
    """The command the skel .zshrc points ``$EDITOR`` at."""
    match = re.search(r"^export EDITOR=(\S+)$", _SKEL_ZSHRC.read_text(), re.MULTILINE)
    assert match, f"{_SKEL_ZSHRC} exports no EDITOR; the guard below has nothing to check"
    return match.group(1)


def test_skel_editor_is_a_command_the_base_image_installs():
    """The base image installs ``vim-tiny``, which registers ``vi`` and no
    ``vim``, so the shipped ``export EDITOR=vim`` resolved to nothing: the
    first ``git commit`` without ``-m`` would have failed."""
    installed = _apt_packages() & _EDITOR_COMMANDS.keys()
    assert installed, f"{_DOCKERFILE_BASE} installs no editor this guard knows about"
    provided = frozenset().union(*(_EDITOR_COMMANDS[pkg] for pkg in installed))
    editor = _skel_editor()
    assert editor in provided, (
        f"skel .zshrc exports EDITOR={editor}, which none of the installed editor "
        f"packages {sorted(installed)} registers; pick one of {sorted(provided)}"
    )
