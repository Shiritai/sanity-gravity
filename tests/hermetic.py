"""Enforce that hermetic tests leave the host alone.

A test that declares none of :data:`OPT_OUTS` is hermetic: it must not
run ``docker`` or ``systemctl`` and must not change files outside
pytest's temp dirs and the tool caches. tests/conftest.py loads this
module as a plugin. Two mechanisms, because neither sees everything:

- An audit hook (PEP 578) sees this process: an exec whose program is
  docker or systemctl, and file-changing events outside the allowed
  roots.
- ``docker`` and ``systemctl`` stubs first on ``PATH`` see everything a
  shell or a child process starts (``shell=True``, ``os.system``,
  ``sanity-cli`` subprocesses, scripts), which the audit hook cannot
  without parsing shell. A stub appends its argv to a per-test record
  and exits nonzero.

Both record, and the test fails at teardown with the list. Raising at
the call site alone is not enough: product code catches ``OSError`` in
several places (``core.proc.try_run`` turns a failed exec into rc=127),
so the exception can be swallowed and the test would still pass. The
hook also raises ``PermissionError`` on a blocked exec so the real
program never starts; writes are only recorded.

While a hermetic test runs, ``tempfile`` points into the session's
basetemp, so ``TemporaryDirectory`` and pytester's capture files stay
inside the allowed roots instead of adding /tmp to them.

A module rather than conftest code: pytester self-tests replay
conftest.py as a second module in this process, and both must share the
one audit hook and its frame stack.
"""
from __future__ import annotations

import itertools
import os
import shlex
import sys
import tempfile
from pathlib import Path

import pytest

#: Markers that take a test out of enforcement. ``requires_image``
#: implies ``requires_docker`` (conftest adds it at collection) and is
#: listed so the rule does not depend on that step having run.
OPT_OUTS = ("requires_docker", "requires_image", "mutates_host")

BLOCKED = frozenset({"docker", "systemctl"})

#: Tool caches, allowed wherever they sit: mutmut runs the suite from
#: mutants/, so anchoring them at the repo root would miss its copies.
_CACHE_DIRS = frozenset(
    {".hypothesis", ".import_linter_cache", ".pytest_cache", "__pycache__"}
)

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC

#: Audit events that change the filesystem, other than ``open``:
#: event -> ((path arg index, dir_fd arg index or None), ...).
#: ``os.rename`` covers ``os.replace`` too; ``os.remove`` covers unlink.
_PATH_EVENTS = {
    "os.chmod": ((0, 2),),
    "os.chown": ((0, 3),),
    "os.link": ((1, 3),),
    "os.mkdir": ((0, 2),),
    "os.remove": ((0, 1),),
    "os.rename": ((0, 2), (1, 3)),
    "os.rmdir": ((0, 1),),
    "os.symlink": ((1, 2),),
    "os.truncate": ((0, None),),
    "os.utime": ((0, 3),),
    "shutil.rmtree": ((0, 1),),
}

_RECORD_ENV = "SANITY_HERMETIC_RECORD"


def _stub(name: str) -> str:
    return (
        "#!/bin/sh\n"
        f"# {name} stand-in on PATH during hermetic tests: record, fail.\n"
        f'printf \'%s\\n\' "{name} $*" >> "${_RECORD_ENV}"\n'
        f'echo "{name} is not available in a hermetic test" >&2\n'
        "exit 1\n"
    )


class _Session:
    """Per-session paths, under that session's basetemp: pytester runs
    and mutmut's repeated pytest.main() calls each get their own."""

    def __init__(self, basetemp: Path) -> None:
        self.roots = (os.path.realpath(basetemp),)
        self.stubs = str(basetemp / "hermetic-stubs")
        # The stdlib tempfile default (/tmp) is pointed here during a
        # hermetic test: TemporaryDirectory users and pytester's capture
        # files then stay inside basetemp instead of widening the roots.
        self.tmp = str(basetemp / "hermetic-tmp")
        os.makedirs(self.stubs, exist_ok=True)
        os.makedirs(self.tmp, exist_ok=True)
        for name in BLOCKED:
            stub = os.path.join(self.stubs, name)
            with open(stub, "w") as fp:
                fp.write(_stub(name))
            os.chmod(stub, 0o755)


class _Frame:
    """One running hermetic test: what it may touch and what it did."""

    def __init__(self, config: pytest.Config, session: _Session) -> None:
        self.config = config
        self.roots = session.roots
        self.record = os.path.join(session.stubs, f"calls-{next(_ids)}.log")
        self.seen: list[str] = []
        self._saved_env = {k: os.environ.get(k) for k in ("PATH", _RECORD_ENV)}
        self._saved_tempdir = tempfile.tempdir
        os.environ["PATH"] = (
            session.stubs + os.pathsep + os.environ.get("PATH", os.defpath)
        )
        os.environ[_RECORD_ENV] = self.record
        tempfile.tempdir = session.tmp

    def restore(self) -> None:
        tempfile.tempdir = self._saved_tempdir
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# A stack, not a single slot: a pytester self-test runs an inner session
# in this process, and the inner test's events belong to the inner test.
_frames: list[_Frame] = []
_ids = itertools.count()
_installed = False
_FRAME = pytest.StashKey[_Frame]()
_SESSION = pytest.StashKey[_Session]()


def is_hermetic(item: pytest.Item) -> bool:
    return all(item.get_closest_marker(m) is None for m in OPT_OUTS)


# -- the audit hook ----------------------------------------------------------


def _text(arg) -> str:
    try:
        return os.fsdecode(arg)
    except TypeError:
        return str(arg)


def _check_exec(frame: _Frame, argv, executable=None) -> None:
    words = [_text(a) for a in argv]
    names = {os.path.basename(words[0])} if words else set()
    if executable is not None:
        names.add(os.path.basename(_text(executable)))
    hit = names & BLOCKED
    if hit:
        command = shlex.join(words)
        frame.seen.append(f"exec {command}")
        raise PermissionError(
            f"hermetic test ran {'/'.join(sorted(hit))}: {command}"
        )


def _allowed(path: str, roots: tuple[str, ...]) -> bool:
    if path == os.devnull:
        return True
    if any(path == r or path.startswith(r + os.sep) for r in roots):
        return True
    return not _CACHE_DIRS.isdisjoint(path.split(os.sep))


def _check_write(frame: _Frame, event: str, path, dir_fd=None) -> None:
    if isinstance(path, int):  # an open fd: its open was checked
        return
    path = _text(path)
    if dir_fd not in (None, -1) and not os.path.isabs(path):
        # Relative to a directory fd (rmtree's inner unlinks). The fd
        # cannot be named cheaply; the rmtree event itself is checked.
        return
    real = os.path.realpath(path)
    if not _allowed(real, frame.roots):
        frame.seen.append(f"{event} {real}")


def _on_open(frame: _Frame, args: tuple) -> None:  # (path, mode, flags)
    if (args[2] or 0) & _WRITE_FLAGS:
        _check_write(frame, "write", args[0])


def _on_path_event(event: str):
    def handler(frame: _Frame, args: tuple) -> None:
        for path_i, fd_i in _PATH_EVENTS[event]:
            fd = None if fd_i is None else args[fd_i]
            _check_write(frame, event, args[path_i], fd)
    return handler


_HANDLERS = {
    "open": _on_open,
    **{event: _on_path_event(event) for event in _PATH_EVENTS},
    # (executable, args, cwd, env)
    "subprocess.Popen": lambda frame, a: _check_exec(frame, a[1], a[0]),
    # (path, argv, env); posix_spawnp raises os.posix_spawn too
    "os.exec": lambda frame, a: _check_exec(frame, a[1], a[0]),
    "os.posix_spawn": lambda frame, a: _check_exec(frame, a[1], a[0]),
    # (mode, path, argv, env)
    "os.spawn": lambda frame, a: _check_exec(frame, a[2], a[1]),
}


def _audit(event: str, args: tuple) -> None:
    # Runs on every audit event in the process (imports, compiles, ...):
    # one truth test and one dict lookup before anything else.
    if _frames:
        handler = _HANDLERS.get(event)
        if handler is not None:
            handler(_frames[-1], args)


# -- per-test frames ---------------------------------------------------------


def _enter(item: pytest.Item) -> None:
    config = item.config
    session = config.stash.get(_SESSION, None)
    if session is None:
        # No public accessor without a fixture request, and this runs
        # before any fixture.
        session = _Session(config._tmp_path_factory.getbasetemp())
        config.stash[_SESSION] = session
    frame = _Frame(config, session)
    item.stash[_FRAME] = frame
    _frames.append(frame)


def _drop_from(index: int) -> None:
    for frame in reversed(_frames[index:]):
        frame.restore()
    del _frames[index:]


def _leave(item: pytest.Item) -> None:
    frame = item.stash.get(_FRAME, None)
    index = next((i for i, f in enumerate(_frames) if f is frame), None)
    if index is None:
        return
    # Frames above ours belong to an inner session that never reached
    # its teardown; drop them too or later events land on them.
    _drop_from(index)

    seen = list(frame.seen)
    if os.path.exists(frame.record):
        with open(frame.record) as fp:
            seen += [f"child exec {line.rstrip()}" for line in fp]
    if seen:
        listing = "\n  ".join(dict.fromkeys(seen))
        pytest.fail(
            "hermetic test touched the host:\n  "
            f"{listing}\n"
            "Keep writes under tmp_path and fake docker/systemctl, or "
            "declare requires_docker / requires_image / mutates_host.",
            pytrace=False,
        )


# -- plugin hooks ------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    # Audit hooks cannot be removed, so one per process; it reads the
    # frame stack, which is empty outside hermetic tests.
    global _installed
    if not _installed:
        sys.addaudithook(_audit)
        _installed = True


def pytest_unconfigure(config: pytest.Config) -> None:
    # A session cut short before a teardown (pytest.exit, Ctrl-C) must
    # not leave its PATH, tempfile dir and frame behind for whatever this
    # process runs next: mutmut keeps going after each pytest.main().
    index = next((i for i, f in enumerate(_frames) if f.config is config), None)
    if index is not None:
        _drop_from(index)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_setup(item: pytest.Item):
    if is_hermetic(item):
        _enter(item)
    return (yield)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_teardown(item: pytest.Item, nextitem):
    try:
        return (yield)
    finally:
        _leave(item)
