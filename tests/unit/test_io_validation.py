"""Tests for ``cli/io.py`` input validation + run_command behaviour.

``validate_username`` and ``validate_project_name`` are the last line of
defence between user input and shell / docker compose contexts. The
regex must not silently widen, and ``run_command`` must respect the
``check`` flag in both capture / non-capture modes.
"""
from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest


from sanity_gravity.cli.io import (
    run_command,
    validate_project_name,
    validate_username,
)


class TestValidateUsername:
    @pytest.mark.parametrize("name", [
        "developer", "_root", "user-123", "u_v",
        "a", "_", "Z9", "u" * 32,  # 32 chars OK
    ])
    def test_accepts_valid(self, name):
        assert validate_username(name) == name

    @pytest.mark.parametrize("name", [
        "", "9user",        # starts with digit
        "user@host",         # @ not allowed
        "user name",         # space
        "user.name",         # period
        "user/name",         # slash
        "user;rm",           # shell metachar
        "u" * 33,            # too long
        "ALL CAPS BUT SPACE",
    ])
    def test_rejects_invalid(self, name):
        with pytest.raises(ValueError, match="Invalid username"):
            validate_username(name)

    def test_rejects_none(self):
        with pytest.raises((ValueError, TypeError)):
            validate_username(None)


class TestValidateProjectName:
    @pytest.mark.parametrize("name", [
        "sanity-gravity", "my-project", "my.project",
        "p1", "Z", "0digit", "a" * 63,
    ])
    def test_accepts_valid(self, name):
        assert validate_project_name(name) == name

    @pytest.mark.parametrize("name", [
        "", "_underscore",   # must start with alnum
        "my project",        # space
        "my/project",        # slash
        "my$project",        # shell metachar
        "a" * 64,            # 64 > 63
    ])
    def test_rejects_invalid(self, name):
        with pytest.raises(ValueError, match="Invalid project name"):
            validate_project_name(name)


class TestRunCommand:
    def test_argv_runs_without_shell(self):
        # Use a benign command that exists everywhere.
        result = run_command(("true",), capture=True, check=False)
        assert result == ""

    def test_capture_returns_stripped_stdout(self):
        out = run_command(("printf", "hello\n"), capture=True)
        assert out == "hello"

    def test_check_true_exits_on_nonzero(self):
        with patch("sanity_gravity.cli.io.print_error") as err:
            with pytest.raises(SystemExit) as ei:
                run_command(("false",), check=True)
            assert ei.value.code != 0
            err.assert_called_once()

    def test_check_false_capture_returns_stdout_on_failure(self):
        # ``check=False`` short-circuits subprocess's own check, but
        # capture mode still uses subprocess.run with check=False so we
        # get an empty string, not an exception.
        out = run_command(("false",), capture=True, check=False)
        assert out == ""

    def test_check_false_noncapture_returns_exit_code(self):
        # check=False callers must be able to observe failure without
        # an exception or process exit (pull aggregates per-variant
        # failures on top of this).
        assert run_command(("false",), check=False) == 1
        assert run_command(("true",), check=False) == 0

    def test_check_true_noncapture_returns_zero_on_success(self):
        assert run_command(("true",), check=True) == 0

    def test_env_merged_with_os_environ(self, monkeypatch):
        monkeypatch.setenv("EXISTING_VAR", "from-os")
        out = run_command(
            ("sh", "-c", "echo $EXISTING_VAR-$INJECTED_VAR"),
            capture=True,
            env={"INJECTED_VAR": "from-arg"},
        )
        assert out == "from-os-from-arg"
