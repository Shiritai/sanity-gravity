"""Tests for ``cli/parser.py`` verb dispatch wiring.

Each subcommand must set ``args.func`` to the correct verb. A typo in
``set_defaults(func=…)`` would otherwise route ``up`` to ``build`` (or
similar) and the existing unit tests wouldn't catch it.
"""
from __future__ import annotations

import argparse

import pytest

from sanity_gravity.cli.parser import build_parser
from sanity_gravity.verbs.build import build
from sanity_gravity.verbs.check import check_prereqs
from sanity_gravity.verbs.ide import ide_cmd
from sanity_gravity.verbs.lifecycle import (
    clean,
    down,
    restart,
    start,
    stop,
)
from sanity_gravity.verbs.open import open_cmd
from sanity_gravity.verbs.proxy import (
    proxy_remove_cmd,
    proxy_setup_cmd,
    proxy_status_cmd,
)
from sanity_gravity.verbs.shell import shell_cmd
from sanity_gravity.verbs.snapshot import snapshot_cmd
from sanity_gravity.verbs.status import (
    list_variants,
    plugins_list,
    status,
)
from sanity_gravity.verbs.sync import sync_config_cmd
from sanity_gravity.verbs.test_suite import test_suite as _test_suite_verb
from sanity_gravity.verbs.up import up
from sanity_gravity.verbs.upgrade import upgrade


def _parse(*argv):
    return build_parser().parse_args(list(argv))


@pytest.mark.parametrize(
    "argv,expected",
    [
        (["up", "-v", "ag-xfce-kasm"], up),
        (["build"], build),
        (["check"], check_prereqs),
        (["down"], down),
        (["stop"], stop),
        (["start"], start),
        (["restart"], restart),
        (["clean"], clean),
        (["status"], status),
        (["list"], list_variants),
        (["upgrade"], upgrade),
        (["shell"], shell_cmd),
        (["open"], open_cmd),
        (["test"], _test_suite_verb),
        (["sync_config"], sync_config_cmd),
        (["snapshot", "--tag", "tagname"], snapshot_cmd),
        (["plugins", "list"], plugins_list),
        (["proxy", "setup"], proxy_setup_cmd),
        (["proxy", "status"], proxy_status_cmd),
        (["proxy", "remove"], proxy_remove_cmd),
        (["ide", "update"], ide_cmd),
        (["ide", "reinstall"], ide_cmd),
    ],
)
def test_subcommand_routes_to_expected_verb(argv, expected):
    args = _parse(*argv)
    assert args.func is expected, (
        f"argv {argv!r} routed to {args.func!r}, expected {expected!r}"
    )


def test_ide_subcommands_set_distinct_ide_command():
    """The two ide subcommands share ``ide_cmd`` but must pass distinct
    ``ide_command`` values via ``set_defaults``."""
    assert _parse("ide", "update").ide_command == "update"
    assert _parse("ide", "reinstall").ide_command == "reinstall"


@pytest.mark.parametrize("action", ["update", "reinstall"])
@pytest.mark.parametrize(
    "argv,expected",
    [
        (["ide", "-n", "X", "{a}"], "X"),
        (["ide", "--name", "X", "{a}"], "X"),
        (["ide", "{a}", "-n", "X"], "X"),
        (["ide", "{a}"], "sanity-gravity"),
    ],
)
def test_ide_name_honored_on_either_side_of_action(action, argv, expected):
    args = _parse(*(a.format(a=action) for a in argv))
    assert args.name == expected


def _nested(parser):
    """Yield (parent, child) for every subparser edge in the tree."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for child in action.choices.values():
                yield parser, child
                yield from _nested(child)


def test_subparser_defaults_never_clobber_parent_options():
    """argparse copies a subparser's defaults over whatever its parent
    already parsed. Any option a parent and its subcommand both accept
    must therefore default to SUPPRESS in the subcommand, or the
    parent-position spelling is silently ignored."""
    offenders = []
    for parent, child in _nested(build_parser()):
        parent_dests = {
            a.dest for a in parent._actions
            if a.option_strings and a.default is not argparse.SUPPRESS
        }
        for a in child._actions:
            if a.dest in parent_dests and a.default is not argparse.SUPPRESS:
                offenders.append(f"{child.prog}: {a.dest}")
        offenders += [
            f"{child.prog}: set_defaults({d})"
            for d in child._defaults if d in parent_dests
        ]
    assert not offenders, offenders


def test_dry_run_flag_lifted_to_top_level():
    """``--dry-run`` is a global flag and must be reachable on ``args``
    regardless of subcommand."""
    args = _parse("--dry-run", "build")
    assert getattr(args, "dry_run", False) is True


def test_log_format_default_text():
    args = _parse("list")
    assert getattr(args, "log_format", "text") == "text"


def test_log_format_json_accepted():
    args = _parse("--log-format", "json", "list")
    assert args.log_format == "json"
