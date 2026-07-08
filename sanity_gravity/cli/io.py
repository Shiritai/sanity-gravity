"""Shared CLI I/O helpers: reporter handle, print_*, run_command, validation.

These are the glue functions that every verb leans on. They are kept in
one small module so verb files don't each carry their own copy.

The module exposes a :data:`_reporter` attribute that :func:`set_reporter`
installs from :mod:`sanity_gravity.cli.main`. When unset (e.g. during
test imports that bypass ``main()``), the print_* helpers fall back to
plain coloured prints so nothing crashes.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys

from sanity_gravity.cli.colors import Colors


# Module-level reporter handle. Built once in ``main()`` and routed
# through every print_* helper. When unset (e.g. during test imports
# that bypass ``main()``), we fall back to plain coloured prints so
# nothing crashes.
_reporter = None


def set_reporter(reporter):
    """Install the active Reporter for this process."""
    global _reporter
    _reporter = reporter


def get_reporter():
    """Return the currently installed reporter (or ``None``)."""
    return _reporter


def print_header(msg):
    if _reporter is not None:
        _reporter.header(msg)
        return
    print(f"{Colors.HEADER}{Colors.BOLD}>>> {msg}{Colors.ENDC}")


def print_success(msg):
    if _reporter is not None:
        _reporter.success(msg)
        return
    print(f"{Colors.OKGREEN}✔ {msg}{Colors.ENDC}")


def print_error(msg):
    if _reporter is not None:
        _reporter.error(msg)
        return
    print(f"{Colors.FAIL}✘ {msg}{Colors.ENDC}")


def print_info(msg):
    if _reporter is not None:
        _reporter.info(msg)
        return
    print(f"{Colors.OKCYAN}ℹ {msg}{Colors.ENDC}")


def print_warning(msg):
    if _reporter is not None:
        _reporter.warning(msg)
        return
    print(f"{Colors.WARNING}⚠ {msg}{Colors.ENDC}")


def print_plain(msg=""):
    """Emit human-readable formatted output (tables, status blocks).

    Use this for verb output that's *not* structured machine data — the
    helper respects ``--log-format=json`` by routing through the
    reporter (which sends Info events to stderr), keeping stdout clean
    for actual JSON payloads. In text mode it prints to stdout exactly
    as bare ``print()`` would, so existing colourised formatting
    (``Colors.BOLD`` etc.) renders unchanged.

    Empty calls (``print_plain()`` for spacing) are passed through as a
    blank line in text mode and dropped in JSON mode.

    For genuine structured payloads (e.g. ``list --json``,
    ``build --list-intermediates --json``) keep using bare ``print()`` —
    those *must* land on stdout in any mode.
    """
    if _reporter is not None:
        # Reporter is in JSON mode → AnsiSink absent; emit as Info so
        # the line shows up on stderr's JsonlSink. In text mode the
        # reporter's AnsiSink would prefix with ``ℹ`` which would
        # clobber the table layout, so we still bare-print there.
        if _reporter.is_text_mode():
            print(msg)
            return
        if msg != "":
            _reporter.info(msg)
        return
    print(msg)


def _format_cmd_for_print(cmd):
    """Render argv list/tuple or str to a human-readable shell-ish form."""
    if isinstance(cmd, (list, tuple)):
        return " ".join(shlex.quote(str(p)) for p in cmd)
    return cmd


def run_command(cmd, cwd=None, capture=False, check=True, env=None, shell=None):
    """Run a subprocess command.

    Accepts either ``Sequence[str]`` argv (preferred, runs with
    ``shell=False``) or ``str`` (legacy: runs with ``shell=True``;
    required for pipes/redirects). The ``shell`` kwarg is inferred from
    the type of ``cmd`` unless explicitly overridden. ``env`` (a mapping)
    is merged with ``os.environ`` so callers no longer need to inline
    ``K=V K=V`` env prefixes.

    Returns the stripped stdout when ``capture=True``, else the exit
    code. With ``check=True`` a failure prints an error and exits the
    process; with ``check=False`` the caller inspects the returned
    stdout / exit code instead (nothing is raised).
    """
    use_shell = shell if shell is not None else isinstance(cmd, str)
    if not capture:
        if _reporter is not None:
            _reporter.command(
                tuple(cmd) if isinstance(cmd, (list, tuple)) else cmd
            )
        else:
            print(f"{Colors.OKBLUE}$ {_format_cmd_for_print(cmd)}{Colors.ENDC}")

    run_env = None
    if env is not None:
        run_env = os.environ.copy()
        run_env.update({k: str(v) for k, v in env.items()})

    try:
        if capture:
            result = subprocess.run(
                cmd, shell=use_shell, cwd=cwd, check=check,
                capture_output=True, text=True, env=run_env,
            )
            return result.stdout.strip()
        result = subprocess.run(
            cmd, shell=use_shell, cwd=cwd, check=check, env=run_env,
        )
        return result.returncode
    except subprocess.CalledProcessError as e:
        # Only reachable with check=True: subprocess.run(check=False)
        # never raises CalledProcessError.
        print_error(f"Command failed with exit code {e.returncode}")
        if capture:
            print(e.stderr)
        sys.exit(e.returncode)


# Username constraint for safe propagation into shell/sed/supervisord configs.
# POSIX-ish: start with alpha/_, then alnum/_/-, up to 32 chars.
_USERNAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_-]{0,31}$")
# Project names map to docker compose project labels; restrict similarly.
_PROJECT_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$")


def validate_username(name):
    """Raise ValueError if ``name`` is unsafe to interpolate into shell/sed contexts."""
    if not name or not _USERNAME_RE.match(name):
        raise ValueError(
            f"Invalid username '{name}': must match {_USERNAME_RE.pattern} "
            "(letters, digits, '_' and '-'; start with letter/underscore; "
            "max 32 chars)"
        )
    return name


def validate_project_name(name):
    """Raise ValueError if ``name`` is unsafe as a docker compose project name."""
    if not name or not _PROJECT_NAME_RE.match(name):
        raise ValueError(
            f"Invalid project name '{name}': must match {_PROJECT_NAME_RE.pattern}"
        )
    return name


def get_uid_gid_user():
    """Return the current user's UID, GID, and Username."""
    import pwd
    uid = os.getuid()
    return uid, os.getgid(), pwd.getpwuid(uid).pw_name
