"""Integration preconditions: one declaration, two policies.

A test that needs the outside world declares it with exactly one of

    @pytest.mark.requires_image("cx-none-ssh")   # needs a built image
    @pytest.mark.requires_docker                 # needs the daemon only
    @pytest.mark.no_image                        # needs nothing (pure python)

and never shells out to ``docker image inspect`` itself. Locally a
missing precondition is a skip carrying the exact build command; in CI
(``SANITY_REQUIRE_IMAGES=1``) a missing official image is a failure,
because a skip there means the build step produced nothing and a green
suite would be a lie. Non-official tags (community/deprecated) stay
skips even under the strict env: CI's ``build all`` never promises
them, so their absence is truthful.
"""
import contextlib
import dataclasses
import functools
import importlib
import os
import pkgutil
import socket
import subprocess
import sys

import pytest

from sanity_gravity.core import proc as _proc
from sanity_gravity.core.proc import Completed
from sanity_gravity.core.registry import OFFICIAL_TAGS
from sanity_gravity.domain.errors import CommandError
from sanity_gravity.domain.naming import Naming
from sanity_gravity.domain.tags import Tag

_STRICT_ENV = "SANITY_REQUIRE_IMAGES"


def pytest_configure(config: pytest.Config) -> None:
    """Register the markers so --strict-markers can reject typos."""
    config.addinivalue_line(
        "markers",
        "requires_image(*tags): needs locally built sanity-gravity images "
        "for the given dimension tags (e.g. 'ag-xfce-kasm'); implies "
        "requires_docker",
    )
    config.addinivalue_line(
        "markers",
        "requires_docker: needs a reachable docker daemon but no prebuilt "
        "sanity-gravity image",
    )
    config.addinivalue_line(
        "markers",
        "no_image: needs neither docker nor an image; declared explicitly so "
        "'no precondition' is distinguishable from 'forgot the precondition'",
    )


def _image_ref(tag: str) -> str:
    # The single image-name renderer in tests/: the production grammar,
    # so the test tree owns no second copy of it.
    return Naming(Tag.parse(tag)).image()


@functools.cache
def _docker_available() -> bool:
    # One probe per session, paid only by tests that declared a docker
    # precondition. A machine with no docker binary reports "absent"
    # rather than exploding inside a fixture.
    try:
        return subprocess.run(
            ("docker", "info"), capture_output=True
        ).returncode == 0
    except OSError:
        return False


@functools.cache
def _image_exists(image: str) -> bool:
    try:
        return subprocess.run(
            ("docker", "image", "inspect", image), capture_output=True
        ).returncode == 0
    except OSError:
        return False


def _declared_tags(node) -> list[str]:
    """Tags this item declared, closest marker first, de-duplicated.

    iter_markers walks function -> class -> module, so a class-level
    declaration is inherited without repeating it on every method.
    """
    seen: list[str] = []
    for mark in node.iter_markers("requires_image"):
        for tag in mark.args:
            if not isinstance(tag, str):
                raise pytest.UsageError(
                    f"{node.nodeid}: requires_image() takes tag strings "
                    f"like 'ag-xfce-kasm', got {tag!r}"
                )
            if tag not in seen:
                seen.append(tag)
    return seen


def _unmet(strict: bool, reason: str) -> None:
    if strict:
        pytest.fail(f"{reason} [{_STRICT_ENV}=1]", pytrace=False)
    pytest.skip(reason)


def _strict() -> bool:
    return os.environ.get(_STRICT_ENV, "").strip().lower() not in (
        "", "0", "false", "no",
    )


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Enforce the declared precondition, at setup time (not at import)."""
    tags = _declared_tags(item)
    needs_docker = tags or item.get_closest_marker("requires_docker") is not None
    if not needs_docker:
        return

    strict = _strict()
    if not _docker_available():
        _unmet(strict, "docker daemon unavailable; `docker info` failed")

    missing = [t for t in tags if not _image_exists(_image_ref(t))]
    if missing:
        images = ", ".join(_image_ref(t) for t in missing)
        builds = " && ".join(f"./sanity-cli build {t}" for t in missing)
        # Strict mode only escalates tags the CI build step promises
        # (the official matrix); a missing community/deprecated image is
        # a truthful skip everywhere. Single-tag form is byte-identical
        # to the legacy skipif reason, so the migration is a pure move
        # of an existing message.
        promised = strict and any(t in OFFICIAL_TAGS for t in missing)
        _unmet(promised, f"{images} not built; run {builds}")


@pytest.fixture
def image(request) -> str:
    """The image ref for a test that declared exactly one tag."""
    tags = _declared_tags(request.node)
    if len(tags) != 1:
        raise pytest.UsageError(
            f"{request.node.nodeid}: the `image` fixture needs exactly one "
            f"requires_image tag, found {tags or 'none'}; use `images` instead"
        )
    return _image_ref(tags[0])


@pytest.fixture
def images(request) -> dict[str, str]:
    """{tag: image_ref} for every tag this test declared."""
    return {t: _image_ref(t) for t in _declared_tags(request.node)}


@pytest.fixture
def free_port():
    """Fixture to find a free port."""
    def _find():
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.bind(('', 0))
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            return s.getsockname()[1]
    return _find


@pytest.fixture(scope="session")
def host_env():
    """Returns a dictionary of host environment variables required for containers."""
    # Mimic sanity-cli logic or use what's likely on host
    # Ideally should query `id -u` etc, but we can assume standard test env or use python
    uid = str(os.getuid())
    gid = str(os.getgid())
    username = os.getenv("USER", "testuser")
    
    return {
        "HOST_UID": uid,
        "HOST_GID": gid,
        "HOST_USER": username,
        "HOST_PASSWORD": "testpassword",  # Standard test password
    }

@pytest.fixture(scope="function")
def docker_cli():
    """Helper to run docker commands."""
    class DockerCLI:
        def run(self, cmd, check=True):
            print(f"DEBUG: Running docker command: {cmd}")
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if check and result.returncode != 0:
                raise RuntimeError(f"Docker command failed: {cmd}\nStderr: {result.stderr}")
            return result
            
        def run_container(self, name, image, ports=None, env=None, detatch=True, rm=True):
            cmd = f"docker run --name {name}"
            if detatch:
                cmd += " -d"
            if rm:
                cmd += " --rm"
            
            if ports:
                for host, container in ports.items():
                    cmd += f" -p {host}:{container}"
            
            if env:
                for k, v in env.items():
                    cmd += f" -e {k}='{v}'"
            
            cmd += f" --shm-size=512m {image}"
            return self.run(cmd)

        def stop(self, name):
            self.run(f"docker rm -f {name}", check=False)

        def exec(self, name, cmd, user=None):
            user_flag = f"-u {user}" if user else ""
            return self.run(f"docker exec {user_flag} {name} {cmd}")

    return DockerCLI()

@pytest.fixture(scope="function")
def clean_container(docker_cli):
    """Factory to register containers for cleanup."""
    containers = []
    
    def _register(name):
        containers.append(name)
        # Ensure it's clean before start
        docker_cli.stop(name)
        return name

    yield _register

    for name in containers:
        print(f"Cleaning up container: {name}")
        docker_cli.stop(name)


# ---------------------------------------------------------------------------
# fake_proc: one scripted fake over the core.proc boundary
# ---------------------------------------------------------------------------
#
# ``core.proc`` is the whole subprocess surface of the package (try_run /
# capture / run_shell). Faking it once, here, replaces the per-file
# monkeypatch forests that each re-invented "what does docker answer?"
# with a different mock shape.
#
# Two properties are deliberate:
#
# 1. An unscripted command is LOUD. A blanket ``lambda *a: Completed(.., 0)``
#    makes every unasked-for command silently succeed, which is exactly how
#    a test goes green while asserting nothing. Here a command no rule covers
#    raises UnscriptedCommand unless the test explicitly opts in with
#    ``fake_proc.default(...)`` -- and even then the fall-through is recorded
#    so ``assert_no_unscripted()`` can pin it.
#
# 2. The names are patched WHERE THEY ARE LOOKED UP. Verbs do
#    ``from sanity_gravity.core.proc import try_run``, so patching
#    ``core.proc.try_run`` alone would not touch the already-imported
#    ``verbs.up.try_run`` binding. ``_proc_bindings`` finds every module
#    attribute that *is* the real function and patches each one; core.proc
#    itself is patched too, so modules imported later also get the fake.

_PROC_FUNCS = ("try_run", "capture", "run_shell")
_REAL_PROC = {name: getattr(_proc, name) for name in _PROC_FUNCS}


class UnscriptedCommand(AssertionError):
    """The code under test ran a command no rule covers."""


@functools.cache
def _import_all_verbs() -> None:
    """Import every ``sanity_gravity`` submodule once.

    ``_proc_bindings`` can only patch bindings that already exist, so the
    set of patched modules must not depend on which test ran first.
    ``__main__`` is skipped: importing it would run the CLI.
    """
    import sanity_gravity

    for info in pkgutil.walk_packages(
        sanity_gravity.__path__, prefix="sanity_gravity."
    ):
        if info.name.rsplit(".", 1)[-1] == "__main__":
            continue
        with contextlib.suppress(Exception):
            importlib.import_module(info.name)


def _proc_bindings() -> list[tuple[object, str]]:
    """Every ``(module, attr)`` whose value IS one of the real proc
    functions -- i.e. every place a ``from ... import try_run`` landed."""
    out: list[tuple[object, str]] = []
    for module in list(sys.modules.values()):
        name = getattr(module, "__name__", "")
        if not name.startswith("sanity_gravity"):
            continue
        for func in _PROC_FUNCS:
            if getattr(module, func, None) is _REAL_PROC[func]:
                out.append((module, func))
    return out


@dataclasses.dataclass(frozen=True)
class ProcCall:
    """One recorded command. ``text`` is what patterns match against."""

    kind: str  # "try_run" | "capture" | "run_shell"
    argv: tuple[str, ...] | str
    kwargs: dict

    @property
    def text(self) -> str:
        if isinstance(self.argv, str):
            return self.argv
        return " ".join(str(a) for a in self.argv)

    def __repr__(self) -> str:  # readable failure output
        return f"<{self.kind} {self.text!r}>"


@dataclasses.dataclass(frozen=True)
class _Outcome:
    rc: int = 0
    stdout: str = ""
    stderr: str = ""

    def __call__(self, call: ProcCall) -> Completed:
        return Completed(
            call.argv, self.rc, stdout=self.stdout, stderr=self.stderr,
        )


class FakeProc:
    """Script subprocess outcomes by command shape; record every call.

        fake_proc.script("docker image inspect", rc=1)
        fake_proc.script("docker ps", stdout="abc|proj-ag-xfce-kasm-1")
        ...
        assert fake_proc.calls_matching("docker build")

    Matching is substring-on-the-rendered-command. When several rules
    match, the LONGEST pattern wins (ties: the most recently scripted),
    so a specific rule can be layered over a general one in any order.
    """

    def __init__(self) -> None:
        self.calls: list[ProcCall] = []
        self.unscripted: list[ProcCall] = []
        self._rules: list[tuple[str, object]] = []
        self._default: object | None = None

    # -- scripting ---------------------------------------------------------

    def script(self, pattern, *, rc=0, stdout="", stderr="", handler=None):
        """Answer any command containing ``pattern``. ``handler`` takes the
        ProcCall and returns a Completed, for outcomes that depend on argv."""
        self._rules.append((pattern, handler or _Outcome(rc, stdout, stderr)))
        return self

    def default(self, *, rc=0, stdout="", stderr="", handler=None):
        """Opt in to a catch-all for unscripted commands.

        Deliberately explicit: without it an unscripted command raises.
        Fall-throughs are still recorded, so ``assert_no_unscripted()``
        keeps working after a default is installed."""
        self._default = handler or _Outcome(rc, stdout, stderr)
        return self

    # -- assertions --------------------------------------------------------

    @property
    def commands(self) -> list[str]:
        return [c.text for c in self.calls]

    def calls_matching(self, pattern) -> list[ProcCall]:
        return [c for c in self.calls if pattern in c.text]

    def ran(self, pattern) -> bool:
        return bool(self.calls_matching(pattern))

    def assert_ran(self, pattern) -> ProcCall:
        matches = self.calls_matching(pattern)
        assert matches, (
            f"expected a command containing {pattern!r}; ran:\n  "
            + "\n  ".join(self.commands or ["(nothing)"])
        )
        return matches[0]

    def assert_never_ran(self, pattern) -> None:
        matches = self.calls_matching(pattern)
        assert not matches, f"unexpected command(s): {matches}"

    def assert_no_unscripted(self) -> None:
        """No command fell through to ``default()``."""
        assert not self.unscripted, (
            "commands ran that no rule scripted:\n  "
            + "\n  ".join(c.text for c in self.unscripted)
        )

    # -- the boundary ------------------------------------------------------

    def _resolve(self, call: ProcCall):
        best, best_key = None, None
        for i, (pattern, outcome) in enumerate(self._rules):
            if pattern in call.text:
                key = (len(pattern), i)
                if best_key is None or key > best_key:
                    best, best_key = outcome, key
        if best is not None:
            return best
        self.unscripted.append(call)
        if self._default is None:
            raise UnscriptedCommand(
                f"unscripted command: {call.text!r}\n"
                f"scripted patterns: "
                f"{[p for p, _ in self._rules] or '(none)'}\n"
                "Script it with fake_proc.script(...), or opt into a "
                "catch-all with fake_proc.default(...)."
            )
        return self._default

    def _try_run(self, argv, **kw) -> Completed:
        call = ProcCall("try_run", tuple(str(a) for a in argv), kw)
        self.calls.append(call)
        res = self._resolve(call)(call)
        if kw.get("capture", True) is False and (res.stdout or res.stderr):
            # Production streams to the terminal and returns empty strings
            # here, so a test asserting on that stdout would be asserting
            # something the code can never see.
            raise AssertionError(
                f"{call.text!r} runs with capture=False, so production "
                "always sees empty stdout/stderr; scripting output for it "
                "would pin a value the code cannot observe."
            )
        return res

    def _capture(self, argv, *, cwd=None, env=None, hint=None) -> str:
        call = ProcCall(
            "capture", tuple(str(a) for a in argv),
            {"cwd": cwd, "env": env, "hint": hint},
        )
        self.calls.append(call)
        # Same contract as the real capture: failure raises, so Ok("")
        # and Err stay distinguishable.
        return self._resolve(call)(call).raise_for_status(hint=hint).stdout

    def _run_shell(self, script, *, cwd=None, env=None, hint=None) -> None:
        call = ProcCall(
            "run_shell", script, {"cwd": cwd, "env": env, "hint": hint},
        )
        self.calls.append(call)
        res = self._resolve(call)(call)
        if not res.ok:
            raise CommandError(script, res.returncode, hint=hint)

    def install(self, monkeypatch) -> None:
        fakes = {
            "try_run": self._try_run,
            "capture": self._capture,
            "run_shell": self._run_shell,
        }
        _import_all_verbs()
        for module, attr in _proc_bindings():
            monkeypatch.setattr(module, attr, fakes[attr])
        # Late importers resolve through core.proc itself.
        for name, fake in fakes.items():
            monkeypatch.setattr(_proc, name, fake)


@pytest.fixture
def fake_proc(monkeypatch) -> FakeProc:
    """The scripted subprocess boundary. See :class:`FakeProc`."""
    fp = FakeProc()
    fp.install(monkeypatch)
    return fp


def container_record(service: str, project: str = "sanity-gravity", *,
                     cid: str = "c1", running: bool = True) -> dict:
    """One discovery record, shaped like find_project_containers returns.

    Built here rather than inline so the shape has one definition: the
    record grew a parsed ``tag`` when the docker-label parse moved to the
    boundary, and hand-written copies in six test modules would each have
    had to learn about it.
    """
    from sanity_gravity.domain.tags import Tag

    return {
        "cid": cid,
        "name": f"{project}-{service}-1",
        "service": service,
        "tag": Tag.parse(service),
        "running": running,
    }
