"""Tests for ``sanity_gravity.cli.main`` argv preprocessing.

``_preprocess_argv`` is the function behind the position-agnostic flags
work in commit 3e10d81. A regression here silently breaks
``sanity-cli status --dry-run`` and friends, so we lock in the contract
with explicit round-trip cases.
"""
from __future__ import annotations

from sanity_gravity.cli.main import _preprocess_argv


class TestPreprocessArgv:
    """Round-trip cases for the global-flag lifter."""

    def test_empty(self):
        assert _preprocess_argv([]) == []

    def test_no_global_flags_passthrough(self):
        assert _preprocess_argv(["status"]) == ["status"]
        assert _preprocess_argv(["build", "ag-xfce-kasm"]) == ["build", "ag-xfce-kasm"]

    def test_dry_run_after_subcommand_lifted_to_front(self):
        assert _preprocess_argv(["status", "--dry-run"]) == ["--dry-run", "status"]
        assert _preprocess_argv(["build", "ag-xfce-kasm", "--dry-run"]) == [
            "--dry-run", "build", "ag-xfce-kasm",
        ]

    def test_dry_run_already_at_front_idempotent(self):
        assert _preprocess_argv(["--dry-run", "status"]) == ["--dry-run", "status"]

    def test_log_format_value_form(self):
        assert _preprocess_argv(["status", "--log-format", "json"]) == [
            "--log-format", "json", "status",
        ]

    def test_log_format_equals_form(self):
        assert _preprocess_argv(["status", "--log-format=json"]) == [
            "--log-format=json", "status",
        ]

    def test_log_format_equals_form_at_front(self):
        # Already correctly placed should pass through.
        assert _preprocess_argv(["--log-format=json", "list"]) == [
            "--log-format=json", "list",
        ]

    def test_explain_rewritten_to_dry_run(self):
        assert _preprocess_argv(["explain", "build"]) == ["--dry-run", "build"]
        assert _preprocess_argv(["explain", "up", "--name", "foo"]) == [
            "--dry-run", "up", "--name", "foo",
        ]

    def test_explain_only(self):
        # ``explain`` with no following verb still rewrites — argparse will
        # then tell the user a verb is required.
        assert _preprocess_argv(["explain"]) == ["--dry-run"]

    def test_explain_inside_args_not_rewritten(self):
        # Only ``argv[0] == "explain"`` triggers the rewrite. A literal
        # ``explain`` later in argv (e.g. as a value) is preserved.
        assert _preprocess_argv(["status", "--name", "explain"]) == [
            "status", "--name", "explain",
        ]

    def test_dry_run_and_log_format_combined(self):
        assert _preprocess_argv(["status", "--dry-run", "--log-format", "json"]) == [
            "--dry-run", "--log-format", "json", "status",
        ]

    def test_log_format_dangling_value_does_not_consume_next(self):
        # Malformed: ``--log-format`` at end. We don't try to be clever;
        # argparse is downstream and will error.
        assert _preprocess_argv(["status", "--log-format"]) == [
            "--log-format", "status",
        ]

    def test_idempotent_double_application(self):
        # Running the preprocessor twice should be a no-op on the second pass.
        once = _preprocess_argv(["build", "ag-xfce-kasm", "--dry-run"])
        assert _preprocess_argv(once) == once
