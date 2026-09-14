"""Guards for the skel .zshrc and the entrypoint that backfills it.

Both halves are image contract rather than user config: the file is
baked in by ``COPY rootfs /`` and the entrypoint copies it into homes
``useradd -m`` never touches. Nothing here is reachable from Python, so
what is pinned is what the source must keep saying; the runtime proof
lives in the container.
"""
from __future__ import annotations

import re

from tests.support import REPO_ROOT

_SKEL_ZSHRC = REPO_ROOT / "sandbox" / "rootfs" / "etc" / "skel" / ".zshrc"
_DOCKERFILE_BASE = REPO_ROOT / "sandbox" / "Dockerfile.base"
_ENTRYPOINT = REPO_ROOT / "sandbox" / "rootfs" / "usr" / "local" / "bin" / "entrypoint.sh"

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


def _seed_block() -> str:
    """The ``if ... fi`` block in entrypoint.sh that seeds the .zshrc."""
    lines = _ENTRYPOINT.read_text().splitlines()
    hits = [n for n, line in enumerate(lines) if "cp /etc/skel/.zshrc" in line]
    assert len(hits) == 1, f"expected one skel .zshrc copy in entrypoint.sh, found {len(hits)}"
    start = max(n for n in range(hits[0]) if lines[n].startswith("if "))
    end = min(n for n in range(hits[0], len(lines)) if lines[n] == "fi")
    return "\n".join(lines[start:end + 1])


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


def test_zshrc_seed_leaves_an_existing_symlink_alone():
    """``[ ! -f ... ]`` follows symlinks, so a dangling .zshrc symlink
    reads as missing and the copy then writes through it and fails.
    Whatever already sits at that path is the user's, resolvable or
    not."""
    block = _seed_block()
    assert "-L" in block, (
        "the skel .zshrc backfill decides on a symlink-following test alone; a "
        f"dangling symlink is both 'missing' and unwritable:\n{block}"
    )


def test_zshrc_seed_cannot_abort_the_entrypoint():
    """entrypoint.sh runs under ``set -e``: an unwritable home must cost
    the user their .zshrc, not their container."""
    copy = next(line for line in _seed_block().splitlines() if "cp /etc/skel/.zshrc" in line)
    assert re.search(r"(^|\s)(if|\|\|)\s", copy.strip()), (
        f"the skel .zshrc copy is unguarded, so a failed copy kills the entrypoint:\n{copy}"
    )
