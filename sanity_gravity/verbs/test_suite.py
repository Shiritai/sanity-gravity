"""``test`` verb: run the project's pytest suite.

The module is named ``test_suite`` (not ``test``) to keep pytest's
default discovery from sweeping it up as a test file.
"""
from __future__ import annotations

import os

from sanity_gravity.cli.io import print_header
from sanity_gravity.domain.errors import SanityError

# The one hint for every missing test dependency: the suite needs the
# whole test extra (pytest, hypothesis, requests, import-linter), so
# naming individual packages would leave the user one failure short.
_INSTALL_HINT = 'pip install -e ".[test]"'


def test_suite(args):
    """Run the test suite using pytest."""
    try:
        import pytest
    except ImportError as e:
        raise SanityError(
            "pytest is not installed.",
            hint=_INSTALL_HINT,
        ) from e

    print_header("Running Test Suite")

    # Disable plugin autoloading to avoid ROS2 environment pollution,
    # then opt the one plugin the suite depends on back in. -p takes an
    # entry-point name: hypothesis's plugin is "hypothesispytest" (bare
    # "hypothesis" would import the package itself, which carries no
    # pytest hooks). No -p for pytest-timeout: the suite has no timeout
    # markers, so reloading it would be a hard requirement with zero use.
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

    pytest_args = ["-v", "-p", "hypothesispytest"]
    if args.target:
        pytest_args.append(args.target)

    try:
        exit_code = int(pytest.main(pytest_args))
    except ImportError as e:
        # pytest.main raises (not returns) when a -p plugin fails to
        # import; a missing dev extra is an expected environment
        # problem, not a bug worth a bare traceback.
        raise SanityError(
            f"pytest could not load a required plugin: {e}",
            hint=_INSTALL_HINT,
        ) from e
    if exit_code != 0:
        raise SanityError(
            f"Test suite failed (pytest exit {exit_code}).",
            exit_code=exit_code,
        )
