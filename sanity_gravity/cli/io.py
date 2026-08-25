"""Shared CLI I/O helpers: reporter accessors, print_*, validation.

These are the glue functions that every verb leans on. They are kept in
one small module so verb files don't each carry their own copy.

The process-wide reporter handle lives in
:mod:`sanity_gravity.core.reporter` (``set_active_reporter`` /
``get_active_reporter``) so core code -- notably the command echo in
:mod:`sanity_gravity.core.proc` -- can reach it without a core -> cli
inversion. ``set_reporter`` / ``get_reporter`` stay as the historical
CLI-facing names. When unset (e.g. during test imports that bypass
``main()``), the print_* helpers fall back to plain coloured prints so
nothing crashes.
"""
from __future__ import annotations

import os
import re

from sanity_gravity.core.colors import Colors
from sanity_gravity.core.reporter import (
    get_active_reporter as get_reporter,
)
from sanity_gravity.core.reporter import (
    set_active_reporter as set_reporter,
)

__all__ = [
    "set_reporter",
    "get_reporter",
    "print_header",
    "print_success",
    "print_error",
    "print_info",
    "print_warning",
    "print_plain",
    "validate_username",
    "validate_project_name",
    "get_uid_gid_user",
]


def print_header(msg):
    reporter = get_reporter()
    if reporter is not None:
        reporter.header(msg)
        return
    print(f"{Colors.HEADER}{Colors.BOLD}>>> {msg}{Colors.ENDC}")


def print_success(msg):
    reporter = get_reporter()
    if reporter is not None:
        reporter.success(msg)
        return
    print(f"{Colors.OKGREEN}✔ {msg}{Colors.ENDC}")


def print_error(msg):
    reporter = get_reporter()
    if reporter is not None:
        reporter.error(msg)
        return
    print(f"{Colors.FAIL}✘ {msg}{Colors.ENDC}")


def print_info(msg):
    reporter = get_reporter()
    if reporter is not None:
        reporter.info(msg)
        return
    print(f"{Colors.OKCYAN}ℹ {msg}{Colors.ENDC}")


def print_warning(msg):
    reporter = get_reporter()
    if reporter is not None:
        reporter.warning(msg)
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
    reporter = get_reporter()
    if reporter is not None:
        # Reporter is in JSON mode → AnsiSink absent; emit as Info so
        # the line shows up on stderr's JsonlSink. In text mode the
        # reporter's AnsiSink would prefix with ``ℹ`` which would
        # clobber the table layout, so we still bare-print there.
        if reporter.is_text_mode():
            print(msg)
            return
        if msg != "":
            reporter.info(msg)
        return
    print(msg)


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
