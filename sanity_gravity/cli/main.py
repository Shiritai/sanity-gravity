"""CLI entry point: parse args, install reporter, dispatch to verb."""
from __future__ import annotations

import atexit
import os
import sys

from sanity_gravity.cli.io import (
    print_error,
    print_info,
    print_plain,
    print_warning,
    set_reporter,
)
from sanity_gravity.cli.parser import build_parser
from sanity_gravity.core.reporter import build_default_reporter
from sanity_gravity.domain.errors import CommandError, SanityError

# Flags accepted at the top level. We pre-process argv so they may also
# appear AFTER the subcommand without confusing argparse, which by
# default attaches a flag to whichever (sub)parser is currently active.
_GLOBAL_BOOL_FLAGS = {"--dry-run"}
_GLOBAL_VALUE_FLAGS = {"--log-format"}


# Verbs that route through the microkernel and genuinely honor
# ``--dry-run`` (the orchestrator + executor short-circuit side effects
# and emit ``WouldExecute`` events). Any verb NOT in this set silently
# does nothing different when ``--dry-run`` is passed; we surface a
# warning rather than letting the user think the command was a preview.
_DRY_RUN_AWARE_COMMANDS: frozenset[str] = frozenset({
    "up", "run",
    "build",
    "down", "stop", "start", "restart", "clean",
    "snapshot",
})


def _preprocess_argv(argv: list[str]) -> list[str]:
    """Two argv massages so the user can't get the syntax wrong:

    1. ``explain`` as the first positional becomes ``--dry-run`` — so
       ``sanity-cli explain status`` is identical to
       ``sanity-cli --dry-run status``. Read-only verbs ignore the
       flag; kernelized verbs honor it.

       **``explain`` is a reserved verb name.** A plugin must not
       register a subcommand named ``explain`` — this rewrite would
       silently shadow it. The contract is intentional: ``explain`` is
       a CLI-level affordance, not a verb in its own right.
    2. Global flags (``--dry-run``, ``--log-format[=…]``) are lifted to
       the front regardless of where the user typed them. This makes
       ``sanity-cli status --dry-run`` work the same as
       ``sanity-cli --dry-run status``.

    Both transformations are idempotent: running on already-correct
    argv leaves it unchanged.
    """
    if argv and argv[0] == "explain":
        argv = ["--dry-run", *argv[1:]]

    front: list[str] = []
    rest: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in _GLOBAL_BOOL_FLAGS:
            front.append(a)
            i += 1
        elif a in _GLOBAL_VALUE_FLAGS:
            front.append(a)
            if i + 1 < len(argv):
                front.append(argv[i + 1])
                i += 2
            else:  # malformed; let argparse complain
                i += 1
        elif "=" in a and a.split("=", 1)[0] in _GLOBAL_VALUE_FLAGS:
            front.append(a)
            i += 1
        else:
            rest.append(a)
            i += 1
    return front + rest


def main():
    """Top-level entry. Wired to ``sanity-cli`` via the shim."""
    parser = build_parser()
    args = parser.parse_args(_preprocess_argv(sys.argv[1:]))

    if not args.command:
        parser.print_help()
        sys.exit(1)

    log_format = getattr(args, "log_format", "text")
    if getattr(args, "json_output", False):
        log_format = "json"

    # Build the reporter once, install it as the module-level handle so
    # legacy print_* helpers route through it, and also expose it on
    # ``args`` for handlers that want to emit events directly.
    reporter = build_default_reporter(
        log_format=log_format,
    )
    set_reporter(reporter)
    args.reporter = reporter
    # Ensure file-backed sinks flush and release their handles even on
    # KeyboardInterrupt / unhandled exception paths.
    atexit.register(reporter.close)
    reporter.start()

    # ``--dry-run`` is only meaningful for kernelized verbs. For every
    # other verb the flag would otherwise be silently ignored, leaving
    # the user thinking they had previewed an operation that actually
    # ran (or would run). Surface a warning instead of failing closed —
    # silent acceptance is the worse failure mode here.
    if getattr(args, "dry_run", False) and args.command not in _DRY_RUN_AWARE_COMMANDS:
        print_warning(
            f"--dry-run has no effect for '{args.command}'; this verb is "
            "read-only or non-kernelized and does not preview side effects."
        )

    try:
        args.func(args)
    except KeyboardInterrupt:
        print()
        print_warning("Interrupted by user.")
        sys.exit(130)
    except SanityError as e:
        # The ONE place that turns a failure into a process exit.
        print_error(str(e))
        if e.hint:
            for line in e.hint.splitlines():
                print_info(line)
        if isinstance(e, CommandError) and e.stderr:
            print_plain(e.stderr.rstrip())
        if os.environ.get("SANITY_DEBUG"):
            import traceback
            traceback.print_exc()
        sys.exit(e.exit_code)
    # NOTE: no blanket ``except Exception``. An unexpected exception is
    # a BUG in this tool and must surface as a full traceback --
    # flattening it to one line costs the stack frame that names the
    # culprit. ``SystemExit`` needs no clause either: it subclasses
    # BaseException and propagates by itself (the sys.exit ratchet is
    # draining the library sites that still raise it).


if __name__ == "__main__":
    main()
