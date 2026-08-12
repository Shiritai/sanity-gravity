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

import subprocess

from sanity_gravity.cli.io import (
    get_reporter,
    print_warning,
    run_command,
)
from sanity_gravity.cli.registry import VALID_TAGS
from sanity_gravity.core.eventbus import EventBus
from sanity_gravity.core.orchestrator import (
    CleanContext,
    DownContext,
    Orchestrator,
    _LIFECYCLE_PHASES,
)
from sanity_gravity.effects.actions import ActionFailedError
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
    ``sanity_home`` volume. Returns the target tag, or ``None`` if the
    service cannot be mapped.
    """
    if service in VALID_TAGS:
        return service
    conn = _LEGACY_CONNECTOR.get(service)
    if conn:
        candidate = f"ag-xfce-{conn}"
        if candidate in VALID_TAGS:
            return candidate
    return None


def get_managed_projects():
    """Return projects managed by this tool (have the specific label)."""
    try:
        cmd = (
            "docker", "ps", "-a",
            "--filter", "label=sanity.gravity.managed=true",
            "--format", '{{.Label "com.docker.compose.project"}}',
        )
        output = run_command(cmd, capture=True, check=False)
        if not output:
            return []
        return sorted(list(set(output.splitlines())))
    except (subprocess.CalledProcessError, SystemExit) as e:
        print_warning(f"Could not list managed projects: {e}")
        return []


def find_project_containers(project_name, include_stopped=False):
    """Discover a project's sandbox containers from compose labels.

    One ``docker ps`` replaces the historical per-``VALID_TAGS`` inspect
    probe: compose stamps each container with project and service
    labels, and the service label is the canonical tag. Results keep
    ``VALID_TAGS`` order so first-match callers retain the deterministic
    choice the probe loop had. "Running" includes paused containers to
    match ``docker inspect``'s ``.State.Running``, which the old probe
    keyed on.

    Returns a list of dicts ``{cid, name, service, running}``.
    """
    try:
        fmt = '{{.ID}}|{{.Names}}|{{.Label "com.docker.compose.service"}}|{{.State}}'
        output = run_command(
            ("docker", "ps", "-a",
             "--filter", f"label=com.docker.compose.project={project_name}",
             "--format", fmt),
            capture=True, check=False,
        )
    except (subprocess.CalledProcessError, SystemExit) as e:
        print_warning(f"Could not list containers for '{project_name}': {e}")
        return []

    records = []
    for line in (output or "").splitlines():
        parts = line.split("|")
        if len(parts) != 4:
            continue
        cid, name, service, state = parts
        if service not in VALID_TAGS:
            continue
        running = state in ("running", "paused")
        if not running and not include_stopped:
            continue
        records.append(
            {"cid": cid, "name": name, "service": service, "running": running}
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

    Returns a list of dicts ``{cid, name, project, service}``.
    """
    try:
        fmt = (
            '{{.ID}}|{{.Names}}|'
            '{{.Label "com.docker.compose.project"}}|'
            '{{.Label "com.docker.compose.service"}}|'
            '{{.Label "sanity.gravity.managed"}}|'
            '{{.Label "sanity.gravity.home-volume"}}'
        )
        output = run_command(
            ("docker", "ps", "-a", "--format", fmt), capture=True, check=False,
        )
        records = []
        if output:
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
    except (subprocess.CalledProcessError, SystemExit) as e:
        print_warning(f"Could not list legacy containers: {e}")
        return []


def get_legacy_projects():
    """Project names that still have at least one un-migrated container."""
    return sorted({r["project"] for r in get_legacy_containers()})


def get_active_projects():
    """Return active Sanity-Gravity project names (Strict Mode)."""
    return get_managed_projects()


def get_project_env(project_name):
    """Retrieve environment variables from a running container of the project."""
    for record in find_project_containers(project_name, include_stopped=True):
        container_name = record["name"]

        try:
            out = run_command(
                ("docker", "inspect", "-f",
                 "{{range .Config.Env}}{{println .}}{{end}}",
                 container_name),
                capture=True, check=False,
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
        except (subprocess.CalledProcessError, ValueError, SystemExit):
            continue

    return {}


def _run_lifecycle(ctx) -> None:
    """Drive a DownContext / CleanContext through the kernel."""
    bus = EventBus()
    register_builtin_lifecycle_hooks(bus)
    executor = build_default_executor(ctx.reporter, dry_run=ctx.dry_run)
    try:
        with Orchestrator(bus, ctx.reporter, executor=executor) as orch:
            orch.run(_LIFECYCLE_PHASES, ctx)
    except ActionFailedError as e:
        import sys as _sys
        _sys.exit(e.result.exit_code or 1)


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


# Explain aliases ------------------------------------------------------------

def explain_down(args):
    args.dry_run = True
    return down(args)


def explain_stop(args):
    args.dry_run = True
    return stop(args)


def explain_start(args):
    args.dry_run = True
    return start(args)


def explain_restart(args):
    args.dry_run = True
    return restart(args)


def explain_clean(args):
    args.dry_run = True
    return clean(args)
