"""ANSI colour constants used by the CLI's text-mode output.

These are kept as a small module so verbs / hooks can import them
without dragging the rest of the CLI in. The :class:`Colors` interface
matches the legacy module-level class so existing call sites don't have
to change.
"""
from __future__ import annotations


class Colors:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
