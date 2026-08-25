"""Type-safe argv builder for subprocess invocation.

CommandBuilder eliminates ``shell=True`` from this codebase by making
correct, list-based argv construction the path of least resistance.

Usage::

    cmd = (
        CommandBuilder("docker", "build")
        .flag("--no-cache", when=no_cache)
        .opt("-f", dockerfile)
        .opt("-t", tag)
        .positional(SANDBOX_DIR)
        .build()
    )
    subprocess.run(cmd, check=True)   # shell=False by default

Design notes:
- ``.opt(flag, value)`` always emits exactly two argv tokens. Pass ``str(int)``
  yourself if you need an integer; we coerce with ``str()`` for convenience.
- ``.opt_if`` / ``.flag(when=...)`` keep call sites linear without ``if``.
- ``.build()`` returns an immutable ``tuple[str, ...]`` so callers cannot
  accidentally mutate the argv after the fact.
"""
from __future__ import annotations

from collections.abc import Iterable


class CommandBuilder:
    """Fluent argv builder. ``shell=True`` should never appear with the result."""

    __slots__ = ("_argv",)

    def __init__(self, *base: str) -> None:
        self._argv: list[str] = [str(b) for b in base]

    def opt(self, flag: str, value: str | int) -> CommandBuilder:
        """Add ``flag value`` (two argv tokens) unconditionally."""
        self._argv.append(flag)
        self._argv.append(str(value))
        return self

    def opt_if(self, flag: str, value: str | int | None, *, when: bool = True) -> CommandBuilder:
        """Add ``flag value`` only when ``when`` is truthy and ``value`` is not None."""
        if when and value is not None:
            self.opt(flag, value)
        return self

    def flag(self, flag: str, *, when: bool = True) -> CommandBuilder:
        """Add a boolean flag (single argv token) when ``when`` is truthy."""
        if when:
            self._argv.append(flag)
        return self

    def positional(self, *vals: str) -> CommandBuilder:
        """Append positional arguments."""
        self._argv.extend(str(v) for v in vals)
        return self

    def extend(self, items: Iterable[str]) -> CommandBuilder:
        """Append an iterable of pre-built argv tokens."""
        self._argv.extend(str(i) for i in items)
        return self

    def build(self) -> tuple[str, ...]:
        """Materialise the immutable argv tuple."""
        return tuple(self._argv)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"CommandBuilder({self._argv!r})"
