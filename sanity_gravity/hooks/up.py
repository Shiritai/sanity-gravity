"""Builtin hooks implementing the up-lifecycle.

Each hook is a plain ``hook(ctx) -> None`` that mirrors a slice of the
legacy inline ``up()`` body. Data flows through :class:`UpContext`
(defined in :mod:`orchestrator`) rather than local variables, so the
kernel can be unit-tested with stubs in place of Docker / FS calls.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from sanity_gravity.effects.actions import RunSubprocess
from sanity_gravity.core.command import CommandBuilder
from sanity_gravity.core.eventbus import EventBus, get_default_bus
from sanity_gravity.domain.phase import Phase
from sanity_gravity.plugins.manifest import PortSpec
from sanity_gravity.plugins.registry import default_registry


def validate_inputs(ctx) -> None:
    """UP_VALIDATE: project / username sanity checks."""
    ctx.deps.validate_project_name(ctx.project)
    ctx.deps.validate_username(ctx.host_user)


def gen_main_compose(ctx) -> None:
    """UP_COMPOSE/100: primary tag-derived compose file."""
    path, _ = ctx.deps.generate_compose_for_tag(str(ctx.tag))
    ctx.compose_files.append(Path(path))


def gen_git_compose(ctx) -> None:
    """UP_COMPOSE/200: optional git-context overlay."""
    git = ctx.deps.generate_git_compose(ctx.host_user, ctx.service_name)
    if git:
        ctx.compose_files.append(Path(git))
        ctx.reporter.info("Git Context Sharing Enabled")


def gen_resource_compose(ctx) -> None:
    """UP_COMPOSE/300: optional cpus/memory overlay."""
    cpus = ctx.env.get("_REQ_CPUS")
    memory = ctx.env.get("_REQ_MEMORY")
    if not cpus and not memory:
        return
    out = ctx.deps.generate_resource_compose(cpus, memory, ctx.service_name)
    if out:
        ctx.compose_files.append(Path(out))
        ctx.reporter.info("Resource Limits Applied")


def _port_specs_by_slug() -> dict[str, PortSpec]:
    """Union of every plugin-declared port spec, keyed by runtime slug.

    The slug is ``PortSpec.legacy_slug`` (or the label when unset) — the
    key ``auto_port_alloc`` writes into ``resolved_ports`` and the
    announce hook reads back. First declaration wins on duplicates; the
    only duplicated slug today is ``ssh``, declared identically by every
    connector.
    """
    out: dict[str, PortSpec] = {}
    for manifest in default_registry().all_manifests():
        for spec in manifest.ports:
            out.setdefault(spec.legacy_slug or spec.label, spec)
    return out


def auto_port_alloc(ctx) -> None:
    """UP_PORT_ALLOC: explicit / ephemeral / auto-fallback decision.

    Mirrors legacy logic exactly: a custom ``--name`` switches every
    non-explicit default to ``"0"``; the default project switches only
    when the default port is already taken (with a warning). The slug
    set, default values, and env var names come from the plugin
    manifests (:class:`PortSpec`), not a kernel-side table, so a new
    connector's ports participate without kernel changes.

    Every known slug is allocated regardless of the active tag (legacy
    behaviour): unused env vars are simply ignored by the tag's compose
    file.
    """
    specs = _port_specs_by_slug()
    requested = ctx.requested_ports.entries
    is_busy = ctx.deps.is_port_in_use

    # CLI-requested slugs first (stable legacy ordering), then any
    # manifest-declared slugs the CLI has no flag for — those start at
    # their manifest default.
    slugs = list(requested) + [s for s in specs if s not in requested]

    resolved: dict[str, str] = {}
    for slug in slugs:
        spec = specs.get(slug)
        req = requested.get(slug)
        value = req.value if req is not None else str(spec.default)
        explicit = req.explicit if req is not None else False
        # A requested slug with no manifest spec has no known default to
        # auto-swap from (and no env var to export): pass it through.
        if spec is not None and not explicit and value == str(spec.default):
            if ctx.project != "sanity-gravity":
                value = "0"
            elif is_busy(spec.default):
                ctx.reporter.warning(
                    f"Default {slug} port {spec.default} is busy. "
                    "Switching to ephemeral."
                )
                value = "0"
        resolved[slug] = value
        if spec is not None:
            ctx.env[spec.env_var] = value

    ctx.resolved_ports = resolved
    ctx.env.update({
        "HOST_UID": str(ctx.host_uid), "HOST_GID": str(ctx.host_gid),
        "HOST_USER": ctx.host_user, "HOST_PASSWORD": ctx.password,
        "VNC_PW": ctx.password, "WORKSPACE_DIR": str(ctx.workspace),
    })

    if ctx.image_override:
        var = f"SANITY_IMAGE_{str(ctx.tag).upper().replace('-', '_')}"
        os.environ[var] = ctx.image_override
        ctx.reporter.info(f"Using Custom Image: {ctx.image_override} for {ctx.tag}")


def _compose_cmd(ctx, *action: str) -> tuple[str, ...]:
    cb = CommandBuilder("docker", "compose", "-p", ctx.project)
    for cf in ctx.compose_files:
        cb.opt("-f", str(cf))
    cb.positional(*action)
    return cb.build()


def docker_compose_up(ctx) -> None:
    """UP_DOCKER/100: enqueue the ``compose up`` action."""
    env = {k: v for k, v in ctx.env.items() if not k.startswith("_")}
    ctx.actions.append(RunSubprocess(
        argv=_compose_cmd(ctx, "up", "-d", ctx.service_name),
        env=env,
    ))


def resolve_ephemeral(ctx) -> None:
    """UP_DOCKER/200: replace ``"0"`` ports with what Docker actually bound.

    Direct ``run_command`` callable on purpose: the hook needs the
    captured stdout to feed back into ``ctx.resolved_ports``. Wrapping
    this as a typed Action with result piping is a future refinement.

    Declared ``skip_in_dry_run=True`` at subscription time so the
    orchestrator drops the hook entirely in dry-run — no docker probe,
    no leftover ``"0"`` ports for announce to print.

    The ports to probe come from the tag's own manifests (connector,
    then agent, then desktop): only those are actually published on the
    container. Once any requested port is ephemeral, every published
    port is re-probed (legacy behaviour) so the announced values always
    reflect what Docker really bound.
    """
    rp = ctx.resolved_ports
    if "0" not in rp.values():
        return

    ctx.reporter.info("Resolving ephemeral ports...")

    def _get(internal: str) -> str:
        try:
            out = ctx.deps.run_command(
                _compose_cmd(ctx, "port", ctx.service_name, internal), capture=True,
            )
            if isinstance(out, str) and ":" in out:
                return out.split(":")[-1]
        except (subprocess.CalledProcessError, SystemExit) as e:
            ctx.reporter.warning(
                f"Could not resolve {ctx.service_name}:{internal} port ({e})"
            )
        return "?"

    reg = default_registry()
    manifests = (
        reg.connectors.get(ctx.tag.connector),
        reg.agents.get(ctx.tag.agent),
        reg.desktops.get(ctx.tag.desktop),
    )
    seen: set[str] = set()
    for manifest in manifests:
        if manifest is None:
            continue
        for spec in manifest.ports:
            slug = spec.legacy_slug or spec.label
            if slug in seen or slug not in rp:
                continue
            seen.add(slug)
            rp[slug] = _get(str(spec.internal))


def sync_config_hook(ctx) -> None:
    """UP_PROVISION: push the host's ``./config/`` into the container.

    Direct ``deps.sync_config`` callable for now — the function mixes
    interactive prompts, file copies, and a tar pipe that need shell.
    Splitting into Actions is tracked in PR #6 backlog.
    """
    if getattr(ctx, "dry_run", False):
        ctx.reporter.info(
            f"» would: sync host config → {ctx.container_name} (skipped in dry-run)"
        )
        return
    ctx.deps.sync_config(ctx.project, ctx.container_name, ctx.host_user)


_ANNOUNCE_LINE_RE = re.compile(r"^([^:]+:\s+)(.+)$")


class _PortsView:
    """Read-only ``{label: value}`` mapping for ``str.format`` templates.

    Wrapping the dict lets the manifest template reference ``{ports.http}``
    via attribute access while still raising on unknown labels (rather
    than silently emitting an empty string). Errors carry the plugin
    slug and the available labels so authors can fix typos without
    having to re-read the manifest.
    """

    def __init__(
        self,
        mapping: dict[str, str],
        *,
        plugin_slug: str | None = None,
    ) -> None:
        self._m = mapping
        self._plugin_slug = plugin_slug

    def __getattr__(self, name: str) -> str:
        # ``__getattr__`` is invoked for ``_m`` / ``_plugin_slug``
        # during ``__init__`` on some Python versions; guard with
        # ``object.__getattribute__`` not to recurse if a typo names
        # one of our own attrs.
        if name in ("_m", "_plugin_slug"):
            raise AttributeError(name)
        try:
            return self._m[name]
        except KeyError as exc:
            available = ", ".join(sorted(self._m)) or "(none)"
            where = (
                f" in {self._plugin_slug!r} announce template"
                if self._plugin_slug else " in announce template"
            )
            raise KeyError(
                f"Unknown port label '{name}'{where}; "
                f"available labels: {available}"
            ) from exc


def _ports_for_announce(ctx, *manifests) -> dict[str, str]:
    """Map manifest port labels onto the runtime-resolved port dict.

    The runtime ``resolved_ports`` dict is keyed by *legacy slug*
    (``ssh`` / ``kasm`` / ``vnc`` / ``novnc``) — the labels
    ``auto_port_alloc`` writes today. Manifest port labels are
    author-defined (``ssh`` / ``http`` / ``vnc`` / ``novnc``). Each
    :class:`PortSpec` carries an optional ``legacy_slug`` field that
    bridges the two: if set, the resolved value is fetched under that
    slug; otherwise we fall back to the manifest's own label (so a
    manifest whose label *happens* to match a slug works without
    declaring it).

    This replaces a previously hardcoded ``legacy_by_internal`` table.
    The kernel no longer knows about specific connector ports; the
    knowledge lives in each connector's manifest.
    """
    rp = ctx.resolved_ports
    out: dict[str, str] = {}
    for manifest in manifests:
        if manifest is None:
            continue
        for port in manifest.ports:
            slug = port.legacy_slug or port.label
            if slug in rp:
                out[port.label] = rp[slug]
    return out


def _render_announce(template: str, **keys) -> dict[str, str]:
    """Render the manifest's announce template into a fields dict.

    The template is a ``str.format``-friendly multi-line block. Each
    non-empty line is split into ``(key, value)`` on the first run of
    ``: <spaces>`` so the AnsiSink keeps producing byte-identical
    ``  KEY:      VALUE`` lines. The rendered ordering preserves the
    template's line ordering.
    """
    rendered = template.format(**keys)
    fields: dict[str, str] = {}
    for line in rendered.splitlines():
        if not line.strip():
            continue
        m = _ANNOUNCE_LINE_RE.match(line)
        if m is None:
            # Lines without a colon-padded label become value-only entries
            # under an empty key — rare path; mostly defensive.
            fields[""] = line
        else:
            fields[m.group(1)] = m.group(2)
    return fields


def announce(ctx) -> None:
    """UP_ANNOUNCE: render announce templates from all plugins of the tag.

    Each of the agent / desktop / connector manifests may carry an
    ``[announce] template = "..."`` block. Templates are rendered
    independently and the resulting fields concatenated into a single
    AccessInfo block (connector first, then agent, then desktop). This
    keeps a familiar single "access details" pane while letting any
    plugin contribute lines (e.g. an agent advertising an extra HTTP
    port, or a desktop noting the resolution).

    In dry-run mode, no container exists and ephemeral ports were not
    resolved, so emit a single planned-outcome summary instead of the
    misleading success + access block.
    """
    rp = getattr(ctx, "resolved_ports", None) or {}
    user = ctx.host_user
    connector_slug = ctx.tag.connector

    if getattr(ctx, "dry_run", False):
        # Defensive: if an earlier phase aborted before ``auto_port_alloc``
        # ran, ``resolved_ports`` will be empty. Don't mislead the user
        # with a bare ``ports:`` line — say so explicitly.
        if rp:
            ports_summary = ", ".join(
                f"{name}={value if value != '0' else '<ephemeral>'}"
                for name, value in rp.items()
            )
        else:
            ports_summary = "<unresolved — earlier phase did not run>"
        ctx.reporter.info(
            f"» would announce: {ctx.tag} ({connector_slug}) — "
            f"ports: {ports_summary}"
        )
        return

    ctx.reporter.success(f"{ctx.tag} is running.")

    reg = default_registry()
    connector_m = reg.get("connector", connector_slug)
    agent_m = reg.agents.get(ctx.tag.agent)
    desktop_m = reg.desktops.get(ctx.tag.desktop)

    ports_map = _ports_for_announce(ctx, connector_m, agent_m, desktop_m)
    base_fmt_kwargs = dict(
        user=user,
        password=ctx.password,
        tag=str(ctx.tag),
        connector=connector_slug,
        container_name=ctx.container_name,
        # The CLI targets an instance by its project name (``--name``), so
        # announce templates can point users at ``./sanity-cli shell
        # --name {project}`` instead of a raw ``docker exec``.
        project=ctx.project,
    )

    merged: dict[str, str] = {}
    for manifest in (connector_m, agent_m, desktop_m):
        if manifest is None or manifest.announce is None:
            continue
        # Per-manifest ``_PortsView`` carries the plugin slug so the
        # KeyError raised on an unknown label tells the author which
        # plugin's template has the typo.
        fmt_kwargs = dict(
            base_fmt_kwargs,
            ports=_PortsView(ports_map, plugin_slug=manifest.slug),
        )
        rendered = _render_announce(manifest.announce.template, **fmt_kwargs)
        # Last-write-wins on collisions — connector goes first so its
        # canonical fields (URL, SSH, User, Pass) keep their values
        # unless a downstream plugin deliberately overrides.
        merged.update(rendered)

    if merged:
        ctx.reporter.access(connector_slug, merged)


def register_builtin_up_hooks(bus: EventBus) -> None:
    """Subscribe builtin up hooks, then splice in plugin-contributed ones.

    Priorities (100/200/300) are spaced so plugin hooks can slot in
    between without renumbering. After the builtins are registered, the
    default bus (where ``@on``-decorated plugin hooks live) is merged in
    so plugin subscriptions fire alongside the builtins.
    """
    # Touch the default registry so plugin ``hooks.py`` files are
    # discovered and their ``@on`` decorators register on the default bus
    # before we splice it in.
    default_registry()

    bus.subscribe(Phase.UP_VALIDATE, validate_inputs, priority=100)
    bus.subscribe(Phase.UP_COMPOSE, gen_main_compose, priority=100)
    bus.subscribe(Phase.UP_COMPOSE, gen_git_compose, priority=200)
    bus.subscribe(Phase.UP_COMPOSE, gen_resource_compose, priority=300)
    bus.subscribe(Phase.UP_PORT_ALLOC, auto_port_alloc, priority=100)
    bus.subscribe(Phase.UP_DOCKER, docker_compose_up, priority=100)
    bus.subscribe(Phase.UP_DOCKER, resolve_ephemeral, priority=200,
                  skip_in_dry_run=True)
    bus.subscribe(Phase.UP_PROVISION, sync_config_hook, priority=100)
    bus.subscribe(Phase.UP_ANNOUNCE, announce, priority=100)

    get_default_bus().merge_into(bus)
