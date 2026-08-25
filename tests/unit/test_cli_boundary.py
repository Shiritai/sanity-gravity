"""The ONE panic boundary: cli/main.py turns SanityError into an exit.

Three contracts:
- a SanityError is rendered (message via print_error, hint via
  print_info) and the process exits with ``e.exit_code``;
- an unexpected exception is a BUG and propagates as a traceback --
  no "Unexpected error" wrapper may dress it up;
- KeyboardInterrupt keeps its historical exit code 130.
"""
from __future__ import annotations

import argparse
from unittest.mock import patch

import pytest

from sanity_gravity.cli import main as main_mod
from sanity_gravity.core.reporter import Reporter
from sanity_gravity.domain.errors import CommandError, SanityError


def _run_main(func, argv=("status",)):
    """Drive main() with a stubbed parser dispatching to ``func``."""
    args = argparse.Namespace(
        command=argv[0], func=func, log_format="text",
        json_output=False, dry_run=False,
    )
    parser = argparse.ArgumentParser()
    parser.parse_args = lambda _argv: args

    with patch.object(main_mod, "build_parser", return_value=parser), \
         patch.object(
             main_mod, "build_default_reporter",
             return_value=Reporter(sinks=[], run_id="t"),
         ), \
         patch.object(main_mod, "set_reporter"), \
         patch.object(main_mod.sys, "argv", ["sanity-cli", *argv]):
        # ``set_reporter`` is stubbed so the module-global reporter
        # handle is not leaked into unrelated tests.
        main_mod.main()


class TestBoundary:
    def test_sanity_error_renders_message_hint_and_exit_code(self):
        def boom(args):
            raise SanityError("nope", hint="do X", exit_code=4)

        with patch.object(main_mod, "print_error") as err, \
             patch.object(main_mod, "print_info") as info:
            with pytest.raises(SystemExit) as ei:
                _run_main(boom)
        assert ei.value.code == 4
        err.assert_called_once_with("nope")
        info.assert_called_once_with("do X")

    def test_multi_line_hint_rendered_line_by_line(self):
        def boom(args):
            raise SanityError("nope", hint="line one\nline two")

        with patch.object(main_mod, "print_error"), \
             patch.object(main_mod, "print_info") as info:
            with pytest.raises(SystemExit) as ei:
                _run_main(boom)
        assert ei.value.code == 1
        assert [c.args[0] for c in info.call_args_list] == [
            "line one", "line two",
        ]

    def test_command_error_renders_stderr_block(self):
        def boom(args):
            raise CommandError(("docker", "pull", "x"), 7, stderr="denied\n")

        with patch.object(main_mod, "print_error") as err, \
             patch.object(main_mod, "print_plain") as plain:
            with pytest.raises(SystemExit) as ei:
                _run_main(boom)
        assert ei.value.code == 7
        err.assert_called_once()
        plain.assert_called_once_with("denied")

    def test_unexpected_exception_propagates_as_bug(self):
        def boom(args):
            raise RuntimeError("bug")

        with pytest.raises(RuntimeError, match="bug"):
            _run_main(boom)

    def test_keyboard_interrupt_exits_130(self):
        def boom(args):
            raise KeyboardInterrupt()

        with patch.object(main_mod, "print_warning"):
            with pytest.raises(SystemExit) as ei:
                _run_main(boom)
        assert ei.value.code == 130
