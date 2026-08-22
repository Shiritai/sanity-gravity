"""The single error root for Sanity-Gravity.

Discipline (Rust semantics, stdlib parts -- no Result library):

- Every *expected* failure is a ``SanityError`` subclass carrying a
  user-facing ``message``, an optional actionable ``hint``, and the
  process ``exit_code`` the CLI should end with.
- Every *unexpected* failure (a bug) stays a plain exception and is
  allowed to reach the terminal as a traceback. We do not dress bugs up
  as user errors.
- ``None`` / empty collections mean "this thing does not exist in the
  domain". They never mean "the operation failed" -- failure raises.
- Library code NEVER calls ``sys.exit``. Only ``cli/main.py`` does, and
  only after catching ``SanityError``.

Compatibility note
------------------
The grammar-level subtypes (``TagError`` in domain/tags.py,
``LayerError`` in domain/layers.py, ``NamingError`` in domain/naming.py,
``ManifestError`` in plugins/manifest.py) deliberately multi-inherit
from ``ValueError``: they are raised through code paths whose existing
callers catch ``ValueError``. Keeping ``ValueError`` in the MRO makes
each re-parenting a zero-behaviour-change step of the strangler
migration. They stay defined next to their grammars -- this module is a
leaf that they import, never the other way around.
"""
from __future__ import annotations

import shlex
from collections.abc import Sequence

__all__ = [
    "SanityError",
    "CommandError",
    "render_argv",
]


def render_argv(argv: Sequence[str] | str) -> str:
    """One copy-pasteable rendering for both command shapes.

    A str command is already shell text and passes through verbatim; a
    tuple renders with ``shlex.quote`` so the printed line can be
    re-run. Owned here so every surface that shows a command (errors,
    the ``$ cmd`` echo, ``Completed``) renders it identically instead
    of keeping hand-copied variants.
    """
    if isinstance(argv, str):
        return argv
    return " ".join(shlex.quote(str(a)) for a in argv)


class SanityError(Exception):
    """Root of every expected failure.

    Parameters
    ----------
    message:
        One line, user-facing, no traceback jargon.
    hint:
        Optional line(s) telling the user what to DO. Copy-pasteable
        commands belong here (e.g. "run ./sanity-cli build ag-xfce-kasm").
    exit_code:
        Process exit code the CLI boundary should use. Defaults to the
        class attribute so subclasses can set a family default.
    """

    exit_code: int = 1  # class-level default; instances may override

    def __init__(
        self,
        message: str,
        *,
        hint: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        if exit_code is not None:
            self.exit_code = exit_code

    def __str__(self) -> str:
        return self.message


class CommandError(SanityError):
    """A subprocess we required to succeed did not.

    Carries the full forensic payload so the boundary handler can render
    a useful block without the caller having to pre-format anything.
    ``exit_code`` mirrors the child's return code (falling back to 1 for
    a zero/unknown rc), which preserves the historical
    ``sys.exit(e.returncode)`` behaviour of the old run_command.
    """

    def __init__(
        self,
        argv: Sequence[str] | str,
        returncode: int,
        *,
        stdout: str = "",
        stderr: str = "",
        message: str | None = None,
        hint: str | None = None,
    ) -> None:
        self.argv: tuple[str, ...] | str = (
            argv if isinstance(argv, str) else tuple(str(a) for a in argv)
        )
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(
            message or self._default_message(),
            hint=hint,
            exit_code=returncode or 1,
        )

    def _default_message(self) -> str:
        head = (self.stderr or self.stdout or "").strip().splitlines()
        detail = f": {head[0]}" if head else ""
        return f"command failed (exit {self.returncode}): {self.rendered}{detail}"

    @property
    def rendered(self) -> str:
        """Copy-pasteable rendering of the failed command."""
        return render_argv(self.argv)
