"""Tests for the announce hook's dry-run sentinel.

When ``ctx.dry_run`` is True and ``resolved_ports`` is empty (because
an earlier phase aborted before ``auto_port_alloc`` ran), the announce
hook must emit ``ports: <unresolved — earlier phase did not run>``
rather than a misleading bare ``ports:``.
"""
from __future__ import annotations

from types import SimpleNamespace

from sanity_gravity.domain.tags import Tag
from sanity_gravity.hooks.up import announce


class _RecorderReporter:
    def __init__(self):
        self.run_id = "ann-test"
        self.messages: list[tuple[str, str]] = []

    def info(self, msg):
        self.messages.append(("info", msg))

    def success(self, msg):
        self.messages.append(("success", msg))

    def warning(self, msg):
        self.messages.append(("warning", msg))

    def access(self, connector, fields):
        self.messages.append(("access", str(fields)))


def _ctx(*, dry_run, resolved_ports):
    return SimpleNamespace(
        tag=Tag(agent="ag", desktop="xfce", connector="kasm"),
        host_user="u",
        password="p",
        project="proj",
        container_name="proj-ag-xfce-kasm-1",
        resolved_ports=resolved_ports,
        dry_run=dry_run,
        reporter=_RecorderReporter(),
    )


def test_dry_run_empty_resolved_ports_uses_sentinel():
    ctx = _ctx(dry_run=True, resolved_ports={})
    announce(ctx)
    msgs = [m for kind, m in ctx.reporter.messages if kind == "info"]
    assert msgs, "expected an info message"
    assert "<unresolved" in msgs[0]
    assert "earlier phase did not run" in msgs[0]


def test_dry_run_missing_resolved_ports_attribute_uses_sentinel():
    """If ``resolved_ports`` is None / missing entirely, the same
    sentinel applies — ``getattr(..., None) or {}`` handles both."""
    ctx = _ctx(dry_run=True, resolved_ports=None)
    announce(ctx)
    msgs = [m for kind, m in ctx.reporter.messages if kind == "info"]
    assert any("<unresolved" in m for m in msgs)


def test_dry_run_with_populated_ports_no_sentinel():
    ctx = _ctx(dry_run=True, resolved_ports={
        "ssh": "2222", "kasm": "8444", "vnc": "5901", "novnc": "6901",
    })
    announce(ctx)
    msgs = [m for kind, m in ctx.reporter.messages if kind == "info"]
    assert msgs
    body = msgs[0]
    assert "<unresolved" not in body
    assert "ssh=2222" in body
    assert "kasm=8444" in body


def test_dry_run_ephemeral_port_renders_placeholder():
    """A resolved value of ``"0"`` represents 'pick an ephemeral port'
    and must render as ``<ephemeral>`` in the dry-run summary."""
    ctx = _ctx(dry_run=True, resolved_ports={"ssh": "0", "kasm": "8444"})
    announce(ctx)
    msgs = [m for kind, m in ctx.reporter.messages if kind == "info"]
    body = msgs[0]
    assert "ssh=<ephemeral>" in body
    assert "kasm=8444" in body


def test_ssh_announce_points_at_sanity_cli_shell():
    """The ssh connector's Shell hint must use ``./sanity-cli shell
    --name {project}`` -- the supported entry point -- not a raw
    ``docker exec``. Guards the {project} placeholder wiring too."""
    ctx = SimpleNamespace(
        tag=Tag(agent="cc", desktop="none", connector="ssh"),
        host_user="dev",
        password="secret",
        project="dev-02",
        container_name="dev-02-cc-none-ssh-1",
        resolved_ports={"ssh": "2222"},
        dry_run=False,
        reporter=_RecorderReporter(),
    )
    announce(ctx)
    access = [m for kind, m in ctx.reporter.messages if kind == "access"]
    assert access, "expected an access block"
    body = access[0]
    assert "./sanity-cli shell --name dev-02" in body
    assert "docker exec" not in body
