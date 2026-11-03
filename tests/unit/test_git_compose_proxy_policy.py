"""The git compose overlay mounts the SSH agent only through the proxy.

Strict policy: the container gets ``/tmp/ssh-agent.sock`` only when the
proxy unit is enabled and its socket exists; otherwise no agent socket
is mounted, and a non-interactive run never sets the proxy up on its
own. The proxy state is faked here; the real systemd round trip is
tests/integration/test_proxy_round_trip.py (``mutates_host``).
"""
from __future__ import annotations

import io
import sys

import pytest
import yaml

from sanity_gravity.compose import generators
from sanity_gravity.core.registry import VALID_TAGS

_AGENT_TARGET = "/tmp/ssh-agent.sock"


class _FakeProxy:
    def __init__(self, enabled: bool, socket_path: str) -> None:
        self.enabled = enabled
        self.socket_path = socket_path

    def is_enabled(self) -> bool:
        return self.enabled

    def get_socket_path(self) -> str:
        return self.socket_path

    def setup(self) -> None:
        raise AssertionError("a non-interactive run must not set up the proxy")


@pytest.fixture
def host(tmp_path, monkeypatch):
    """A fake HOME with a .gitconfig, a scratch cwd, no TTY on stdin.

    The .gitconfig makes the overlay exist in every case, so "no agent
    mount" is checked on a real file instead of passing because nothing
    was written.
    """
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text("[user]\n\tname = t\n")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(work)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    return home, work


def _generate(monkeypatch, work, proxy) -> dict:
    monkeypatch.setattr(generators, "ProxyManager", lambda: proxy)
    out = generators.generate_git_compose("testuser")
    assert out is not None
    path = work / out
    assert path.is_file()
    return yaml.safe_load(path.read_text())["services"]


def test_enabled_proxy_socket_is_mounted_in_every_service(host, monkeypatch):
    home, work = host
    socket_path = home / ".gemini" / "bridge" / "ssh.sock"
    socket_path.parent.mkdir(parents=True)
    socket_path.touch()

    services = _generate(monkeypatch, work, _FakeProxy(True, str(socket_path)))

    assert set(services) == set(VALID_TAGS)
    for name, svc in services.items():
        assert svc["volumes"] == [
            f"{home}/.gitconfig:/home/testuser/.gitconfig",
            f"{socket_path}:{_AGENT_TARGET}",
        ], name
        assert svc["environment"] == [f"SSH_AUTH_SOCK={_AGENT_TARGET}"], name


@pytest.mark.parametrize(
    ("enabled", "make_socket"),
    [(False, True), (True, False), (False, False)],
    ids=["unit-not-enabled", "socket-missing", "neither"],
)
def test_missing_proxy_mounts_no_agent_socket(host, monkeypatch,
                                              enabled, make_socket):
    home, work = host
    socket_path = home / ".gemini" / "bridge" / "ssh.sock"
    if make_socket:
        socket_path.parent.mkdir(parents=True)
        socket_path.touch()

    services = _generate(monkeypatch, work, _FakeProxy(enabled, str(socket_path)))

    assert set(services) == set(VALID_TAGS)
    for name, svc in services.items():
        assert svc["volumes"] == [
            f"{home}/.gitconfig:/home/testuser/.gitconfig",
        ], name
        assert "environment" not in svc, name
    assert "ssh-agent.sock" not in (work / "config" / "docker-compose.git.yml").read_text()
