"""Subprocess boundary: three functions, three intents, one error type.

    capture(argv)   -> str        # stdout IS the value. Failure raises;
                                  # Ok("") and Err are distinguishable.
    try_run(argv)   -> Completed  # I will inspect the outcome myself;
                                  # .raise_for_status() escalates when
                                  # "I need this to succeed".
    run_shell(str)  -> None       # I genuinely need a shell.

``run_shell`` is an explicit, greppable act rather than a consequence
of passing a str (the old ``run_command`` inferred ``shell=True`` from
``isinstance(cmd, str)``).

This lives in ``core/`` and not ``cli/`` on purpose: subprocess
execution is a core capability, and the "library code never sys.exits"
ratchet only lines up with the layering if the executor is not welded to
the presentation glue.
"""
from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sanity_gravity.domain.errors import CommandError, render_argv

Argv = Sequence[str]

# Matches the legacy Colors.OKBLUE echo of run_command; self-contained
# like the reporter's AnsiSink escapes so core does not import cli.
_OKBLUE = "\033[94m"
_ENDC = "\033[0m"


@dataclass(frozen=True)
class Completed:
    """Outcome of a command whose failure the caller wants to inspect."""

    argv: tuple[str, ...] | str
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def raise_for_status(self, *, hint: str | None = None) -> Completed:
        """Escalate a non-zero outcome; return self otherwise (chainable)."""
        if not self.ok:
            raise CommandError(
                self.argv, self.returncode,
                stdout=self.stdout, stderr=self.stderr, hint=hint,
            )
        return self


def _merged_env(env: Mapping[str, str] | None) -> dict[str, str] | None:
    if env is None:
        return None
    merged = os.environ.copy()
    merged.update({k: str(v) for k, v in env.items()})
    return merged


def _echo(argv: tuple[str, ...] | str) -> None:
    """Emit the ``$ cmd`` line through the active reporter.

    Falls back to a bare coloured print when no reporter is installed
    (e.g. helpers invoked directly in tests), mirroring the legacy
    run_command echo.
    """
    from sanity_gravity.core.reporter import get_active_reporter

    reporter = get_active_reporter()
    if reporter is not None:
        reporter.command(argv)
        return
    print(f"{_OKBLUE}$ {render_argv(argv)}{_ENDC}")


def try_run(
    argv: Argv,
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    capture: bool = True,
    echo: bool = False,
) -> Completed:
    """Run a command and hand the caller the full outcome. Never raises
    on a non-zero exit; a missing binary comes back as rc=127.

    ``capture=False`` streams the child's output to the terminal (e.g.
    docker pull progress bars); stdout/stderr are then empty strings.
    """
    cmd = tuple(str(a) for a in argv)
    if echo:
        _echo(cmd)
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, env=_merged_env(env), check=False,
            capture_output=capture, text=True,
        )
    except FileNotFoundError as exc:
        return Completed(cmd, 127, stderr=str(exc))
    return Completed(
        cmd, proc.returncode,
        stdout=(proc.stdout or "").strip(),
        stderr=(proc.stderr or "").strip(),
    )


def capture(
    argv: Argv,
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    hint: str | None = None,
) -> str:
    """Run a command whose stdout is the value. Raises CommandError on
    failure, so "" unambiguously means the command succeeded and said
    nothing."""
    return try_run(
        argv, cwd=cwd, env=env, capture=True, echo=False,
    ).raise_for_status(hint=hint).stdout


def run_shell(
    script: str,
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    hint: str | None = None,
) -> None:
    """Run a genuine shell script (pipes / redirects). One caller today:
    the tar-pipe in verbs/sync.py. Every argument interpolated into
    ``script`` must already be shlex.quote()d by the caller."""
    _echo(script)
    rc = subprocess.call(script, shell=True, cwd=cwd, env=_merged_env(env))
    if rc != 0:
        raise CommandError(script, rc, hint=hint)
