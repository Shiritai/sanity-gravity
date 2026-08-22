"""Action runner with introspection and replay-friendly logging.

Hooks build :class:`~actions.Action` values; the orchestrator drains
them after each phase and hands them to :class:`Executor`. The Executor
emits structured events around every action and (when given a
``run_dir``) appends one JSON line per action to ``actions.jsonl``.

When ``dry_run=True`` the Executor short-circuits ``execute()`` and
emits a :class:`~events.WouldExecute` event instead. This is the
mechanism behind ``--dry-run`` and ``explain``.
"""
from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import IO, Any

from sanity_gravity.effects.actions import (
    Action,
    ActionFailedError,
    ActionResult,
    ActionRuntime,
    RunSubprocess,
    SystemRuntime,
)
from sanity_gravity.events import (
    ActionFailed,
    ActionFinished,
    ActionStarted,
    WouldExecute,
)

_DRY_RUN_RESULT = ActionResult(exit_code=0, duration_ms=0)


class Executor:
    """Run :class:`Action` instances, narrate via :class:`Reporter`."""

    def __init__(
        self,
        runtime: ActionRuntime,
        reporter,
        *,
        dry_run: bool = False,
        run_dir: Path | None = None,
    ) -> None:
        self.runtime = runtime
        self.reporter = reporter
        self.dry_run = dry_run
        self.run_dir = run_dir
        self.history: list[tuple[Action, ActionResult]] = []
        self._actions_fp: IO[str] | None = None
        self._actions_broken = False

    # -- public API ---------------------------------------------------

    def run(self, action: Action, *, phase=None) -> ActionResult:
        phase_str = str(phase.value) if phase is not None and hasattr(phase, "value") else (
            str(phase) if phase is not None else None
        )
        argv: tuple[str, ...] | str
        if isinstance(action, RunSubprocess):
            argv = action.argv
        else:
            argv = action.explain()

        if self.dry_run:
            self.reporter.emit_now(
                WouldExecute, phase=phase_str,
                explain_str=action.explain(),
                action_type=type(action).__name__,
            )
            self.history.append((action, _DRY_RUN_RESULT))
            self._append_actions_log(action, _DRY_RUN_RESULT, phase_str, dry=True)
            return _DRY_RUN_RESULT

        self.reporter.emit_now(
            ActionStarted, phase=phase_str,
            action_type=type(action).__name__,
            argv=argv,
        )
        try:
            result = action.execute(self.runtime)
        except FileNotFoundError as exc:
            result = ActionResult(exit_code=127, stderr=str(exc))
        except OSError as exc:
            result = ActionResult(exit_code=1, stderr=str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            result = ActionResult(exit_code=1, stderr=f"{type(exc).__name__}: {exc}")

        self.history.append((action, result))
        self._append_actions_log(action, result, phase_str, dry=False)

        self.reporter.emit_now(
            ActionFinished, phase=phase_str,
            action_type=type(action).__name__,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
        )

        check = getattr(action, "check", True)
        if check and result.exit_code != 0:
            stderr_tail = (result.stderr or "").splitlines()
            tail = "\n             ".join(stderr_tail[-5:]) if stderr_tail else ""
            self.reporter.emit_now(
                ActionFailed, level="error", phase=phase_str,
                action_type=type(action).__name__,
                argv=argv,
                exit_code=result.exit_code,
                stderr_tail=tail,
                explain_str=action.explain(),
            )
            raise ActionFailedError(action, result, phase=phase_str)
        return result

    def drain(self, actions: Iterable[Action], *, phase=None) -> list[ActionResult]:
        results: list[ActionResult] = []
        for action in actions:
            results.append(self.run(action, phase=phase))
        return results

    def close(self) -> None:
        fp = self._actions_fp
        self._actions_fp = None
        if fp is not None:
            try:
                fp.close()
            except OSError:
                pass

    def __enter__(self) -> Executor:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    # -- internals ----------------------------------------------------

    def _ensure_actions_log(self) -> IO[str] | None:
        if self.run_dir is None or self._actions_broken:
            return None
        if self._actions_fp is not None:
            return self._actions_fp
        try:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            self._actions_fp = (self.run_dir / "actions.jsonl").open(
                "a", encoding="utf-8",
            )
        except OSError as exc:
            sys.stderr.write(
                f"warning: actions log unavailable ({exc}); continuing\n"
            )
            self._actions_broken = True
            return None
        return self._actions_fp

    def _append_actions_log(
        self, action: Action, result: ActionResult,
        phase_str: str | None, *, dry: bool,
    ) -> None:
        fp = self._ensure_actions_log()
        if fp is None:
            return
        try:
            payload = {
                "phase": phase_str,
                "dry_run": dry,
                **action.to_log_dict(),
                "result": {
                    "exit": result.exit_code,
                    "duration_ms": result.duration_ms,
                },
            }
            fp.write(json.dumps(payload, default=str) + "\n")
            fp.flush()
        except OSError:
            self._actions_broken = True


def build_default_executor(
    reporter,
    *,
    dry_run: bool = False,
    base: Path | None = None,
) -> Executor:
    """Construct an Executor with a real :class:`SystemRuntime`.

    The executor's ``run_dir`` is whatever the reporter says — there is
    one source of truth for per-run paths, and that source is the
    reporter. ``base`` is honored for tests that override the reporter's
    base via the same mechanism, but in production both default to
    ``~/.cache/sanity-gravity/runs/<run_id>``.
    """
    if base is not None:
        run_dir = base / reporter.run_id
    else:
        run_dir = reporter.run_dir
    return Executor(
        runtime=SystemRuntime(), reporter=reporter,
        dry_run=dry_run, run_dir=run_dir,
    )
