"""``down`` / ``stop`` / ``start`` / ``restart`` / ``clean`` verbs.

The phase loop ``lifecycle.before → lifecycle.docker → lifecycle.after``
is published by :class:`Orchestrator`; per-phase behaviour lives in
:mod:`sanity_gravity.hooks.lifecycle`. ``clean`` reuses the same phase
sequence with a
``CleanContext`` that adds a ``[y/N]`` prompt + extra docker-compose
args (``-v --rmi local --remove-orphans``).

Plus the project-discovery helpers (managed/legacy/active project lists)
and ``get_project_env`` — shared with ``upgrade`` and ``sync_config``.
"""
from __future__ import annotations

from sanity_gravity.core.eventbus import EventBus
from sanity_gravity.core.orchestrator import (
    _LIFECYCLE_PHASES,
    CleanContext,
    DownContext,
    Orchestrator,
)
from sanity_gravity.core.proc import capture
from sanity_gravity.core.registry import VALID_TAGS
from sanity_gravity.core.reporter import get_active_reporter as get_reporter
from sanity_gravity.domain.tags import Tag
from sanity_gravity.effects.executor import build_default_executor
from sanity_gravity.hooks.lifecycle import register_builtin_lifecycle_hooks

# Flat service names used by containers created before the modular-tag
# layout (PR #10). They map to ``ag-xfce-<connector>`` on migration.
LEGACY_SERVICES = {"core", "kasm", "vnc"}
_LEGACY_CONNECTOR = {"core": "ssh", "kasm": "kasm", "vnc": "vnc"}


def legacy_target_tag(service):
    """Map an old / managed service name to the tag it migrates to.

    A flat legacy service (core/kasm/vnc) becomes ``ag-xfce-<connector>``
    (migration assumes the default agent=antigravity, desktop=xfce; only
    the connector carries over). A service that is already a valid tag —
    a managed container created before the persistent-home model — keeps
    its tag and migrates in place, the point being only to attach the
    ``sanity_home`` volume. Returns the target tag as a value, or
    ``None`` if the service cannot be mapped - a legacy service name is
    a boundary string, and this is where it becomes a Tag.
    """
    if service in VALID_TAGS:
        return Tag.parse(service)
    conn = _LEGACY_CONNECTOR.get(service)
    if conn:
        candidate = Tag(agent="ag", desktop="xfce", connector=conn)
        if str(candidate) in VALID_TAGS:
            return candidate
    return None


def get_managed_projects():
    """Return projects managed by this tool (have the specific label).

    ``[]`` means only "no managed projects exist"; a broken docker
    raises CommandError (the old warn-and-return-[] collapse made the
    two indistinguishable).
    """
    output = capture((
        "docker", "ps", "-a",
        "--filter", "label=sanity.gravity.managed=true",
        "--format", '{{.Label "com.docker.compose.project"}}',
    ))
    if not output:
        return []
    return sorted(set(output.splitlines()))


def find_project_containers(project_name, include_stopped=False):
    """Discover a project's sandbox containers from compose labels.

    One ``docker ps`` replaces the historical per-``VALID_TAGS`` inspect
    probe: compose stamps each container with project and service
    labels, and the service label is the canonical tag. Results keep
    ``VALID_TAGS`` order so first-match callers retain the deterministic
    choice the probe loop had. "Running" includes paused containers to
    match ``docker inspect``'s ``.State.Running``, which the old probe
    keyed on.

    Returns a list of dicts ``{cid, name, service, running}``; raises
    CommandError when docker cannot answer.
    """
    fmt = '{{.ID}}|{{.Names}}|{{.Label "com.docker.compose.service"}}|{{.State}}'
    output = capture(
        ("docker", "ps", "-a",
         "--filter", f"label=com.docker.compose.project={project_name}",
         "--format", fmt),
    )

    records = []
    for line in output.splitlines():
        parts = line.split("|")
        if len(parts) != 4:
            continue
        cid, name, service, state = parts
        if service not in VALID_TAGS:
            continue
        running = state in ("running", "paused")
        if not running and not include_stopped:
            continue
        # The service label IS the tag: this is the boundary where the
        # string becomes a value, so consumers read record["tag"] instead
        # of parsing the label again in each verb. Membership in
        # VALID_TAGS above means the parse cannot fail.
        records.append(
            {
                "cid": cid,
                "name": name,
                "service": service,
                "tag": Tag.parse(service),
                "running": running,
            }
        )
    records.sort(key=lambda r: VALID_TAGS.index(r["service"]))
    return records


def get_legacy_containers():
    """Sanity containers that still need migration to the persistent-home model.

    "Needs migration" means a container that is ours — managed label, or
    a recognizable sanity service name — but does NOT carry the
    ``sanity.gravity.home-volume`` label, i.e. its agent state still
    lives in the ephemeral writable layer instead of the per-project
    ``sanity_home`` volume.

    This keys off the home-volume marker rather than comparing the
    service against ``VALID_TAGS``: genuine legacy containers have flat
    service names (``core`` / ``kasm`` / ``vnc``) that are not in the
    *new* tag list, so the old ``service in VALID_TAGS`` test never
    matched the very containers it was meant to find.

    Returns a list of dicts ``{cid, name, project, service}``; raises
    CommandError when docker cannot answer.
    """
    fmt = (
        '{{.ID}}|{{.Names}}|'
        '{{.Label "com.docker.compose.project"}}|'
        '{{.Label "com.docker.compose.service"}}|'
        '{{.Label "sanity.gravity.managed"}}|'
        '{{.Label "sanity.gravity.home-volume"}}'
    )
    output = capture(("docker", "ps", "-a", "--format", fmt))
    records = []
    for line in output.splitlines():
        parts = line.split("|")
        if len(parts) != 6:
            continue
        cid, name, project, service, managed, home_vol = parts
        if not project or not service:
            continue
        is_ours = (
            managed == "true"
            or service in LEGACY_SERVICES
            or service in VALID_TAGS
        )
        if is_ours and home_vol != "true":
            records.append({
                "cid": cid, "name": name,
                "project": project, "service": service,
            })
    return records


def get_legacy_projects():
    """Project names that still have at least one un-migrated container."""
    return sorted({r["project"] for r in get_legacy_containers()})


def get_active_projects():
    """Return active Sanity-Gravity project names (Strict Mode)."""
    return get_managed_projects()


def get_project_env(project_name):
    """Retrieve environment variables from a running container of the project.

    ``{}`` means only "no container carries a recognized env var"; a
    docker failure raises CommandError. (The old except tuple also
    named ValueError -- unreachable, the '=' guard below precedes the
    split -- and SystemExit, both fossils of the run_command era.)
    """
    for record in find_project_containers(project_name, include_stopped=True):
        container_name = record["name"]

        out = capture(
            ("docker", "inspect", "-f",
             "{{range .Config.Env}}{{println .}}{{end}}",
             container_name),
        )
        if not out:
            continue

        env_map = {}
        for line in out.splitlines():
            if "=" in line:
                key, val = line.split("=", 1)
                if key in ["SSH_HOST_PORT", "KASM_PORT", "VNC_PORT",
                           "NOVNC_PORT", "HOST_UID", "HOST_GID",
                           "HOST_USER", "HOST_PASSWORD", "VNC_PW"]:
                    env_map[key] = val

        if env_map:
            return env_map

    return {}


def _run_lifecycle(ctx) -> None:
    """Drive a DownContext / CleanContext through the kernel.

    ActionFailedError propagates to the CLI boundary, which exits with
    the action result's code.
    """
    bus = EventBus()
    register_builtin_lifecycle_hooks(bus)
    executor = build_default_executor(ctx.reporter, dry_run=ctx.dry_run)
    with Orchestrator(bus, ctx.reporter, executor=executor) as orch:
        orch.run(_LIFECYCLE_PHASES, ctx)


def _make_down_ctx(args, action: str, *, check_existence: bool) -> DownContext:
    reporter = getattr(args, "reporter", None) or get_reporter()
    return DownContext(
        project=args.name,
        action=action,
        reporter=reporter,
        check_existence=check_existence,
        dry_run=bool(getattr(args, "dry_run", False)),
    )


def down(args):
    """Stop and remove all sandbox containers (docker compose down)."""
    _run_lifecycle(_make_down_ctx(args, "down", check_existence=True))


def stop(args):
    """Stop sandbox containers without removing them (docker compose stop)."""
    _run_lifecycle(_make_down_ctx(args, "stop", check_existence=False))


def start(args):
    """Start existing stopped containers (docker compose start)."""
    _run_lifecycle(_make_down_ctx(args, "start", check_existence=False))


def restart(args):
    """Restart sandbox containers (docker compose restart)."""
    _run_lifecycle(_make_down_ctx(args, "restart", check_existence=False))


def clean(args):
    """Deep cleanup: remove containers, volumes, local images and orphans."""
    reporter = getattr(args, "reporter", None) or get_reporter()
    ctx = CleanContext(
        project=args.name,
        action="down",
        reporter=reporter,
        check_existence=False,
        dry_run=bool(getattr(args, "dry_run", False)),
        extra_action_args=("-v", "--rmi", "local", "--remove-orphans"),
        force=bool(getattr(args, "force", False)),
    )
    _run_lifecycle(ctx)
