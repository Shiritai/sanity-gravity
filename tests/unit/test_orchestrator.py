"""Tests for the up-lifecycle orchestrator (PR #4).

These tests do *not* invoke Docker. We construct an :class:`UpContext`
with stubbed :class:`Deps` and :class:`Reporter`, run the orchestrator,
and assert on the recorded calls. This is enough to verify:

- phases run in the documented order,
- ctx mutations from earlier hooks are visible to later ones,
- the builtin hook set produces the same Docker invocations the legacy
  ``up()`` did (without actually invoking Docker).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from sanity_gravity.core.eventbus import EventBus
from sanity_gravity.core.orchestrator import (
    _UP_PHASES,
    Deps,
    Orchestrator,
    PortRequest,
    RequestedPort,
    UpContext,
)
from sanity_gravity.core.proc import Completed
from sanity_gravity.domain.phase import Phase
from sanity_gravity.domain.tags import Tag
from sanity_gravity.hooks import up as up_hooks
from sanity_gravity.hooks.up import register_builtin_up_hooks
from sanity_gravity.plugins.manifest import PluginManifest, PortSpec

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _RecorderReporter:
    """Minimal Reporter stand-in. Captures messages by category."""

    def __init__(self):
        self.run_id = "test-run"
        self.calls: list[tuple[str, tuple, dict]] = []

    def _record(self, kind):
        def _fn(*a, **kw):
            self.calls.append((kind, a, kw))
        return _fn

    def __getattr__(self, name):
        return self._record(name)


def _make_deps(**overrides):
    """Build a stub :class:`Deps` where every hook is a recorder.

    ``overrides`` lets a single test replace one stub with custom
    behaviour while leaving the rest as no-ops.
    """
    calls = []

    def _rec(name, ret=None):
        def _fn(*a, **kw):
            calls.append((name, a, kw))
            return ret
        return _fn

    base = dict(
        validate_username=_rec("validate_username", "u"),
        validate_project_name=_rec("validate_project_name", "p"),
        generate_compose_for_tag=_rec(
            "generate_compose_for_tag", ("config/docker-compose.tag.yml", "tag")
        ),
        generate_git_compose=_rec("generate_git_compose", None),
        generate_resource_compose=_rec("generate_resource_compose", None),
        sync_config=_rec("sync_config"),
        is_port_in_use=_rec("is_port_in_use", False),
        try_run=_rec("try_run", Completed(("true",), 0)),
    )
    base.update(overrides)
    deps = Deps(**base)
    return deps, calls


def _make_ctx(deps, *, project="sanity-gravity", connector="kasm",
              ssh_explicit=False):
    return UpContext(
        tag=Tag(agent="ag", desktop="xfce", connector=connector),
        project=project,
        host_user="developer",
        host_uid=1000,
        host_gid=1000,
        password="antigravity",
        workspace=Path("/tmp/ws"),
        image_override=None,
        requested_ports=PortRequest(entries={
            "ssh": RequestedPort("2222", explicit=ssh_explicit),
            "kasm": RequestedPort("8444"),
            "vnc": RequestedPort("5901"),
            "novnc": RequestedPort("6901"),
        }),
        deps=deps,
        reporter=_RecorderReporter(),
    )


# ---------------------------------------------------------------------------
# Orchestrator core
# ---------------------------------------------------------------------------


def test_orchestrator_runs_phases_in_documented_order():
    bus = EventBus()
    fired: list[Phase] = []
    for ph in _UP_PHASES:
        bus.subscribe(ph, lambda ctx, p=ph: fired.append(p))

    deps, _ = _make_deps()
    ctx = _make_ctx(deps)
    Orchestrator(bus, ctx.reporter).run(_UP_PHASES, ctx)

    assert fired == list(_UP_PHASES)


def test_orchestrator_ctx_mutations_propagate():
    """A hook in UP_COMPOSE writes; a hook in UP_DOCKER reads."""
    bus = EventBus()

    def writer(ctx):
        ctx.compose_files.append(Path("/tmp/extra.yml"))

    seen: list[Path] = []

    def reader(ctx):
        seen.extend(ctx.compose_files)

    bus.subscribe(Phase.UP_COMPOSE, writer, priority=50)
    bus.subscribe(Phase.UP_DOCKER, reader, priority=50)

    deps, _ = _make_deps()
    ctx = _make_ctx(deps)
    Orchestrator(bus, ctx.reporter).run(_UP_PHASES, ctx)
    assert Path("/tmp/extra.yml") in seen


# ---------------------------------------------------------------------------
# Builtin hooks (full sanity flow, mocked Docker)
# ---------------------------------------------------------------------------


def test_full_up_flow_invokes_expected_deps_in_order():
    bus = EventBus()
    register_builtin_up_hooks(bus)

    deps, calls = _make_deps()
    ctx = _make_ctx(deps)
    Orchestrator(bus, ctx.reporter).run(_UP_PHASES, ctx)

    # PR #5: ``docker compose up`` is now enqueued as an Action rather
    # than shelling out directly. ``sync_config`` still runs
    # eagerly (its tar-pipe + interactive prompts haven't migrated).
    names = [c[0] for c in calls]
    assert names.index("validate_project_name") < names.index("generate_compose_for_tag")
    assert "sync_config" in names
    # Exactly one action should have been queued: the compose-up.
    assert len(ctx.actions) == 1
    from sanity_gravity.effects.actions import RunSubprocess  # noqa: PLC0415

    assert isinstance(ctx.actions[0], RunSubprocess)
    assert "up" in ctx.actions[0].argv and "-d" in ctx.actions[0].argv


def test_compose_files_collected_from_compose_phase():
    bus = EventBus()
    register_builtin_up_hooks(bus)

    deps, _ = _make_deps(
        generate_git_compose=lambda u, s: "config/git.yml",
    )
    ctx = _make_ctx(deps)
    ctx.env["_REQ_CPUS"] = "1.5"  # force resource overlay

    # Replace generate_resource_compose to return a file
    deps.generate_resource_compose = lambda c, m, s: "config/resources.yml"

    Orchestrator(bus, ctx.reporter).run(_UP_PHASES, ctx)

    paths = [str(p) for p in ctx.compose_files]
    assert "config/docker-compose.tag.yml" in paths
    assert "config/git.yml" in paths
    assert "config/resources.yml" in paths


def _snapshot_after_port_alloc(bus):
    """Capture ``resolved_ports`` immediately after UP_PORT_ALLOC.

    A high-priority hook on UP_DOCKER (before ``resolve_ephemeral``)
    grabs the dict so we can assert on the auto-port-alloc decision
    without the post-Docker discovery overwriting it.
    """
    snap: dict[str, str] = {}

    def _grab(ctx):
        snap.update(ctx.resolved_ports)

    bus.subscribe(Phase.UP_DOCKER, _grab, priority=50)
    return snap


def test_port_alloc_custom_project_switches_defaults_to_ephemeral():
    bus = EventBus()
    register_builtin_up_hooks(bus)
    snap = _snapshot_after_port_alloc(bus)

    deps, _ = _make_deps()
    ctx = _make_ctx(deps, project="my-other-project")
    Orchestrator(bus, ctx.reporter).run(_UP_PHASES, ctx)
    # All four defaults should have flipped to "0".
    assert snap == {"ssh": "0", "kasm": "0", "vnc": "0", "novnc": "0"}


def test_port_alloc_default_project_keeps_free_ports_explicit():
    bus = EventBus()
    register_builtin_up_hooks(bus)
    snap = _snapshot_after_port_alloc(bus)

    deps, _ = _make_deps()  # is_port_in_use returns False
    ctx = _make_ctx(deps)
    Orchestrator(bus, ctx.reporter).run(_UP_PHASES, ctx)
    assert snap["ssh"] == "2222"
    assert snap["kasm"] == "8444"


def test_port_alloc_default_project_busy_port_falls_back_to_ephemeral():
    bus = EventBus()
    register_builtin_up_hooks(bus)
    snap = _snapshot_after_port_alloc(bus)

    busy = {2222: True, 8444: False, 5901: False, 6901: False}
    deps, _ = _make_deps(is_port_in_use=lambda p: busy.get(p, False))
    ctx = _make_ctx(deps)
    Orchestrator(bus, ctx.reporter).run(_UP_PHASES, ctx)
    assert snap["ssh"] == "0"
    assert snap["kasm"] == "8444"


def test_explicit_port_flag_disables_auto_swap():
    bus = EventBus()
    register_builtin_up_hooks(bus)
    snap = _snapshot_after_port_alloc(bus)

    deps, _ = _make_deps()
    ctx = _make_ctx(deps, project="my-other-project", ssh_explicit=True)
    Orchestrator(bus, ctx.reporter).run(_UP_PHASES, ctx)
    # Custom project would normally flip ssh to "0"; explicit flag pins it.
    assert snap["ssh"] == "2222"
    assert snap["kasm"] == "0"


class _StubRegistry:
    """Registry stand-in exposing only what the up hooks consult."""

    def __init__(self, *manifests):
        self.agents = {m.slug: m for m in manifests if m.kind == "agent"}
        self.desktops = {m.slug: m for m in manifests if m.kind == "desktop"}
        self.connectors = {
            m.slug: m for m in manifests if m.kind == "connector"
        }

    def all_manifests(self):
        return [
            *self.agents.values(),
            *self.desktops.values(),
            *self.connectors.values(),
        ]


def _connector_manifest(slug, *ports):
    return PluginManifest(
        slug=slug, name=slug, kind="connector", api_version="1",
        provides=(), requires=(), dockerfile="Dockerfile", ports=ports,
    )


def test_port_alloc_allocates_manifest_declared_new_slug(monkeypatch):
    """A port slug the CLI has no flag for is still allocated: the slug
    set, default, and env var all come from the plugin manifest."""
    obs = _connector_manifest(
        "obs",
        PortSpec(label="metrics", internal=9100, default=9100,
                 env_var="METRICS_PORT"),
        PortSpec(label="ssh", internal=22, default=2222,
                 env_var="SSH_HOST_PORT", legacy_slug="ssh"),
    )
    monkeypatch.setattr(up_hooks, "default_registry", lambda: _StubRegistry(obs))

    deps, _ = _make_deps()
    ctx = _make_ctx(deps, project="my-other-project")
    up_hooks.auto_port_alloc(ctx)

    # Manifest-backed slugs flip their non-explicit defaults to ephemeral
    # on a custom project; the manifest-only slug behaves like the rest.
    assert ctx.resolved_ports["ssh"] == "0"
    assert ctx.resolved_ports["metrics"] == "0"
    assert ctx.env["SSH_HOST_PORT"] == "0"
    assert ctx.env["METRICS_PORT"] == "0"
    # Requested slugs without a manifest spec pass through untouched and
    # export no env var (no default is known to auto-swap from).
    assert ctx.resolved_ports["kasm"] == "8444"
    assert "KASM_PORT" not in ctx.env


def test_port_alloc_manifest_slug_busy_default_falls_back(monkeypatch):
    """The default-project busy check probes the manifest default."""
    obs = _connector_manifest(
        "obs",
        PortSpec(label="metrics", internal=9100, default=9100,
                 env_var="METRICS_PORT"),
    )
    monkeypatch.setattr(up_hooks, "default_registry", lambda: _StubRegistry(obs))

    deps, _ = _make_deps(is_port_in_use=lambda p: p == 9100)
    ctx = _make_ctx(deps)
    up_hooks.auto_port_alloc(ctx)

    assert ctx.resolved_ports["metrics"] == "0"
    assert ctx.env["METRICS_PORT"] == "0"


def test_resolve_ephemeral_probes_manifest_internal_ports(monkeypatch):
    """The ports to probe come from the tag's manifests, not a kernel
    table of per-connector internal ports."""
    obs = _connector_manifest(
        "obs",
        PortSpec(label="metrics", internal=9100, default=9100,
                 env_var="METRICS_PORT"),
    )
    monkeypatch.setattr(up_hooks, "default_registry", lambda: _StubRegistry(obs))

    port_calls = []

    def _run(cmd, **kw):
        if isinstance(cmd, tuple) and "port" in cmd:
            port_calls.append(cmd)
            return Completed(tuple(cmd), 0, stdout="0.0.0.0:41000")
        return Completed(tuple(cmd), 0)

    deps, _ = _make_deps(try_run=_run)
    ctx = _make_ctx(deps, connector="obs")
    ctx.resolved_ports = {"metrics": "0"}
    up_hooks.resolve_ephemeral(ctx)

    assert [cmd[-1] for cmd in port_calls] == ["9100"]
    assert ctx.resolved_ports["metrics"] == "41000"


def test_resolve_ephemeral_only_runs_when_port_is_zero():
    bus = EventBus()
    register_builtin_up_hooks(bus)

    port_calls = []

    def _run(cmd, **kw):
        # Distinguish ``port`` lookups from the initial ``up -d``.
        if isinstance(cmd, tuple) and "port" in cmd:
            port_calls.append(cmd)
            return Completed(tuple(cmd), 0, stdout="0.0.0.0:32768")
        return Completed(tuple(cmd), 0)

    deps, _ = _make_deps(try_run=_run)
    ctx = _make_ctx(deps, project="other")  # forces ephemeral
    Orchestrator(bus, ctx.reporter).run(_UP_PHASES, ctx)
    # We requested kasm-connector; expect lookups for 22 + 8444.
    looked_up = [cmd[-1] for cmd in port_calls]
    assert "22" in looked_up
    assert "8444" in looked_up


def test_announce_emits_access_for_active_connector():
    bus = EventBus()
    register_builtin_up_hooks(bus)

    deps, _ = _make_deps()
    ctx = _make_ctx(deps, connector="ssh")
    Orchestrator(bus, ctx.reporter).run(_UP_PHASES, ctx)
    access_calls = [c for c in ctx.reporter.calls if c[0] == "access"]
    assert len(access_calls) == 1
    kind, args, kwargs = access_calls[0]
    assert args[0] == "ssh"
    fields = args[1]
    assert any("ssh -p" in v for v in fields.values())


def test_announce_in_dry_run_summarises_without_success_or_access():
    """Dry-run must not claim the container is running or print AccessInfo.

    The ``up`` flow short-circuits Docker side effects in dry-run mode
    (resolve_ephemeral / sync_config skip themselves and the executor
    refuses to run actions). The announce hook must follow suit: emit a
    single planned-outcome line rather than the misleading legacy
    ``is running`` + Access block.
    """
    bus = EventBus()
    register_builtin_up_hooks(bus)

    deps, _ = _make_deps()
    ctx = _make_ctx(deps, project="other")  # forces ephemeral on kasm/ssh
    ctx.dry_run = True
    Orchestrator(bus, ctx.reporter).run(_UP_PHASES, ctx)

    kinds = [c[0] for c in ctx.reporter.calls]
    assert "success" not in kinds
    assert "access" not in kinds

    info_messages = [
        c[1][0] for c in ctx.reporter.calls if c[0] == "info" and c[1]
    ]
    would = [m for m in info_messages if "would announce" in m]
    assert len(would) == 1, info_messages
    msg = would[0]
    assert "ag-xfce-kasm" in msg
    assert "kasm" in msg
    # Ports flipped to "0" by auto_port_alloc must surface as <ephemeral>.
    assert "<ephemeral>" in msg
    assert "=0" not in msg


def test_validate_inputs_propagates_value_error():
    bus = EventBus()
    register_builtin_up_hooks(bus)

    def _bad(_):
        raise ValueError("invalid project")

    deps, _ = _make_deps(validate_project_name=_bad)
    ctx = _make_ctx(deps)
    with pytest.raises(ValueError, match="invalid project"):
        Orchestrator(bus, ctx.reporter).run(_UP_PHASES, ctx)


def test_phase_tick_lines_emitted_to_reporter():
    bus = EventBus()
    register_builtin_up_hooks(bus)

    deps, _ = _make_deps()
    ctx = _make_ctx(deps)
    Orchestrator(bus, ctx.reporter).run(_UP_PHASES, ctx)

    info_messages = [
        c[1][0] for c in ctx.reporter.calls if c[0] == "info" and c[1]
    ]
    # Each phase should have surfaced a ``[up.<step>]`` tick.
    for ph in _UP_PHASES:
        assert f"[{ph.value}]" in info_messages
