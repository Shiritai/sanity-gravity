"""The subprocess boundary: three functions, three intents, one error.

The load-bearing distinction: ``capture`` raises on failure, so ``""``
unambiguously means "the command succeeded and said nothing". The old
``run_command(capture=True, check=False)`` returned ``""`` for both --
that collapse is the disease this module exists to cure.
"""
from __future__ import annotations

import pytest

from sanity_gravity.core import proc
from sanity_gravity.domain.errors import CommandError


class TestCapture:
    def test_returns_stripped_stdout(self):
        assert proc.capture(("printf", "hello\n")) == "hello"

    def test_ok_empty_is_a_legal_value(self):
        assert proc.capture(("true",)) == ""

    def test_failure_raises_instead_of_collapsing_to_empty(self):
        # Contrast pin: the same input used to return "" through
        # run_command(("false",), capture=True, check=False). Err and
        # Ok("") are now different types.
        with pytest.raises(CommandError) as ei:
            proc.capture(("false",))
        assert ei.value.returncode == 1
        assert ei.value.exit_code == 1

    def test_hint_is_carried_onto_the_error(self):
        with pytest.raises(CommandError) as ei:
            proc.capture(("false",), hint="do X")
        assert ei.value.hint == "do X"

    def test_env_merged_with_os_environ(self, monkeypatch):
        monkeypatch.setenv("EXISTING_VAR", "from-os")
        out = proc.capture(
            ("sh", "-c", "echo $EXISTING_VAR-$INJECTED_VAR"),
            env={"INJECTED_VAR": "from-arg"},
        )
        assert out == "from-os-from-arg"


class TestTryRun:
    def test_nonzero_is_an_outcome_not_an_exception(self):
        res = proc.try_run(("false",))
        assert res.ok is False
        assert res.returncode == 1

    def test_success_carries_stdout_and_stderr(self):
        res = proc.try_run(("sh", "-c", "echo out; echo err >&2"))
        assert res.ok is True
        assert res.stdout == "out"
        assert res.stderr == "err"

    def test_missing_binary_is_rc_127_not_an_exception(self):
        res = proc.try_run(("no-such-binary-xyz-sanity",))
        assert res.returncode == 127
        assert res.ok is False

    def test_raise_for_status_escalates(self):
        with pytest.raises(CommandError) as ei:
            proc.try_run(("false",)).raise_for_status(hint="h")
        assert ei.value.returncode == 1
        assert ei.value.hint == "h"
        # And chains through on success.
        assert proc.try_run(("true",)).raise_for_status().ok is True

    def test_streaming_escalation_keeps_the_child_rc(self):
        """The former run() intent, spelled in its surviving form."""
        with pytest.raises(CommandError) as ei:
            proc.try_run(
                ("sh", "-c", "exit 3"), capture=False, echo=True,
            ).raise_for_status()
        assert ei.value.returncode == 3
        assert ei.value.exit_code == 3

    def test_streaming_escalation_missing_binary_is_127(self):
        with pytest.raises(CommandError) as ei:
            proc.try_run(
                ("no-such-binary-xyz-sanity",), capture=False,
            ).raise_for_status()
        assert ei.value.returncode == 127


class TestRunShell:
    def test_shell_is_an_explicit_act(self):
        # A pipe only a shell can run; the argv functions never infer
        # shell=True from the argument type.
        assert proc.run_shell("printf x | grep -q x") is None

    def test_failure_raises(self):
        with pytest.raises(CommandError) as ei:
            proc.run_shell("exit 5")
        assert ei.value.returncode == 5


def test_the_boundary_surface_is_exactly_three_functions():
    """Two fossils stay dead: run_command (the shell-inferring,
    str|int-returning god-function) and run (try_run().raise_for_status
    minus the choice), along with the two Completed conveniences nothing
    consumed (rendered, error). The module's 'three functions, three
    intents' docstring is a checked claim, not a wish."""
    for fossil in ("run_command", "run"):
        assert not hasattr(proc, fossil)
    for fossil in ("rendered", "error"):
        assert not hasattr(proc.Completed, fossil)


def test_echo_routes_through_the_active_reporter():
    from sanity_gravity.core.reporter import (
        Reporter,
        get_active_reporter,
        set_active_reporter,
    )

    class _Recorder(Reporter):
        commands: list = []

        def command(self, argv):
            self.commands.append(argv)

    rec = _Recorder(sinks=[], run_id="t")
    previous = get_active_reporter()
    set_active_reporter(rec)
    try:
        proc.try_run(("true",), capture=False, echo=True)
    finally:
        set_active_reporter(previous)
    assert rec.commands == [("true",)]
