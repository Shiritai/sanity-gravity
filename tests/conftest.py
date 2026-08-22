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
import functools
import os
import socket
import subprocess

import pytest

from sanity_gravity.core.registry import OFFICIAL_TAGS
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
