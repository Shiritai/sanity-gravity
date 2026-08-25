"""Effect-First Action types.

Every external side effect first becomes an immutable :class:`Action`
value, then gets executed by an :class:`~executor.Executor`. This split
unlocks ``--dry-run``, ``explain``, replay, and structured failure UX.

Design points
-------------
- ``Action`` is an ABC. Concrete subclasses are frozen dataclasses so
  they JSON-round-trip cleanly and never mutate after construction.
- ``explain(self) -> str`` produces a copy-pasteable shell-ish line for
  dry-run / failure messages.
- ``execute(self, runtime) -> ActionResult`` performs the side effect
  through the :class:`ActionRuntime` indirection so tests can swap a
  fake runtime in without touching the filesystem or Docker.
- The set is intentionally small (~4 types). New needs should be
  expressed by composing existing actions before adding a new type.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import time
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from sanity_gravity.domain.errors import SanityError


@dataclass(frozen=True)
class ActionResult:
    """Outcome of running one Action."""

    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0


class ActionRuntime(Protocol):
    """Thin holder for the I/O modules an Action needs.

    The default implementation is :class:`SystemRuntime`; tests pass
    :class:`FakeRuntime` (or any compatible duck type) to capture argv
    without executing anything.
    """

    def run_subprocess(
        self,
        argv: tuple[str, ...],
        *,
        env: Mapping[str, str] | None,
        cwd: str | None,
        capture: bool,
    ) -> ActionResult: ...

    def write_file(self, path: str, content: str, mode: int) -> None: ...

    def make_dirs(self, path: str, mode: int) -> None: ...

    def sleep(self, seconds: float) -> None: ...

    def now(self) -> float: ...


class SystemRuntime:
    """Real-system :class:`ActionRuntime` backed by stdlib modules."""

    def run_subprocess(
        self,
        argv,
        *,
        env=None,
        cwd=None,
        capture=False,
    ) -> ActionResult:
        run_env = None
        if env is not None:
            run_env = os.environ.copy()
            run_env.update({k: str(v) for k, v in env.items()})
        start = time.monotonic()
        if capture:
            proc = subprocess.run(
                argv, cwd=cwd, check=False,
                capture_output=True, text=True, env=run_env,
            )
            dur = int((time.monotonic() - start) * 1000)
            return ActionResult(
                exit_code=proc.returncode,
                stdout=(proc.stdout or "").strip(),
                stderr=(proc.stderr or "").strip(),
                duration_ms=dur,
            )
        try:
            rc = subprocess.call(argv, cwd=cwd, env=run_env)
        except FileNotFoundError as exc:
            dur = int((time.monotonic() - start) * 1000)
            return ActionResult(exit_code=127, stderr=str(exc), duration_ms=dur)
        dur = int((time.monotonic() - start) * 1000)
        return ActionResult(exit_code=rc, duration_ms=dur)

    def write_file(self, path: str, content: str, mode: int) -> None:
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(content)
        try:
            os.chmod(path, mode)
        except OSError:
            pass

    def make_dirs(self, path: str, mode: int) -> None:
        os.makedirs(path, mode=mode, exist_ok=True)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def now(self) -> float:
        return time.monotonic()


class Action(ABC):
    """Base class for declarative side effects."""

    @abstractmethod
    def explain(self) -> str:
        """Render a copy-pasteable shell-ish representation."""

    @abstractmethod
    def execute(self, runtime: ActionRuntime) -> ActionResult:
        """Perform the side effect via ``runtime``."""

    def to_log_dict(self) -> dict:
        """Best-effort, JSON-serialisable summary for ``actions.jsonl``."""
        return {"action_type": type(self).__name__, "explain": self.explain()}


@dataclass(frozen=True)
class RunSubprocess(Action):
    """Execute an argv through subprocess - never a shell.

    This single Action covers every docker / docker-compose / system
    binary invocation in the codebase. The one genuine shell need (the
    tar-pipe in ``sync_config``) goes through ``core.proc.run_shell``;
    keeping no shell affordance here means an Action cannot smuggle
    ``shell=True`` in through a field.

    ``check`` is consumed by the Executor (raise vs hand back the
    result), not by the runtime: execution is the same either way.
    """

    argv: tuple[str, ...] = ()
    env: Mapping[str, str] | None = None
    cwd: str | None = None
    capture: bool = False
    check: bool = True

    def explain(self) -> str:
        return " ".join(shlex.quote(str(a)) for a in self.argv)

    def execute(self, runtime: ActionRuntime) -> ActionResult:
        return runtime.run_subprocess(
            self.argv, env=self.env, cwd=self.cwd, capture=self.capture,
        )

    def to_log_dict(self) -> dict:
        return {
            "action_type": "RunSubprocess",
            "argv": list(self.argv),
            "cwd": self.cwd,
            "capture": self.capture,
            "check": self.check,
        }


@dataclass(frozen=True)
class WriteFile(Action):
    """Create or overwrite a file with the given content."""

    path: str = ""
    content: str = ""
    mode: int = 0o644

    def explain(self) -> str:
        size = len(self.content)
        return f"write {self.path} ({size} bytes, mode={oct(self.mode)})"

    def execute(self, runtime: ActionRuntime) -> ActionResult:
        runtime.write_file(self.path, self.content, self.mode)
        return ActionResult(exit_code=0)

    def to_log_dict(self) -> dict:
        return {
            "action_type": "WriteFile",
            "path": self.path,
            "size": len(self.content),
            "mode": oct(self.mode),
        }


@dataclass(frozen=True)
class MakeDirs(Action):
    """Create a directory (parents included). Idempotent."""

    path: str = ""
    mode: int = 0o755

    def explain(self) -> str:
        return f"mkdir -p {shlex.quote(self.path)}"

    def execute(self, runtime: ActionRuntime) -> ActionResult:
        runtime.make_dirs(self.path, self.mode)
        return ActionResult(exit_code=0)

    def to_log_dict(self) -> dict:
        return {"action_type": "MakeDirs", "path": self.path, "mode": oct(self.mode)}


@dataclass(frozen=True)
class WaitForUserInContainer(Action):
    """Poll ``id -u <username>`` inside a container until it succeeds.

    Abstracts the inline 30-iteration loop in ``sync_config`` so dry-run
    can describe it as a single line of intent.
    """

    container: str = ""
    username: str = ""
    timeout_s: int = 30

    def explain(self) -> str:
        return (
            f"wait-for-user container={shlex.quote(self.container)} "
            f"user={shlex.quote(self.username)} timeout={self.timeout_s}s"
        )

    def execute(self, runtime: ActionRuntime) -> ActionResult:
        deadline = runtime.now() + self.timeout_s
        last_stderr = ""
        while True:
            res = runtime.run_subprocess(
                ("docker", "exec", self.container, "id", "-u", self.username),
                env=None, cwd=None, capture=True,
            )
            if res.stdout and res.stdout.strip().isdigit():
                return ActionResult(exit_code=0, stdout=res.stdout)
            last_stderr = res.stderr
            if runtime.now() >= deadline:
                return ActionResult(exit_code=1, stderr=last_stderr or "timeout")
            runtime.sleep(1.0)

    def to_log_dict(self) -> dict:
        return {
            "action_type": "WaitForUserInContainer",
            "container": self.container,
            "username": self.username,
            "timeout_s": self.timeout_s,
        }


class ActionFailedError(SanityError):
    """Raised when an action's ``execute`` returns non-zero exit_code.

    Carries the offending action plus its result so the CLI boundary can
    render a structured failure block. Under the SanityError root:
    ``exit_code`` mirrors the action result's code (0 -> 1), so the
    boundary reproduces the historical ``sys.exit(e.result.exit_code or
    1)`` behaviour without any per-verb wrapper.
    """

    def __init__(self, action: Action, result: ActionResult, *,
                 phase: str | None = None) -> None:
        self.action = action
        self.result = result
        self.phase = phase
        super().__init__(
            f"action failed: {action.explain()} (exit={result.exit_code})",
            exit_code=result.exit_code or 1,
        )
