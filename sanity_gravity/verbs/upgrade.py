"""``upgrade`` verb: losslessly migrate containers to the persistent-home model.

A container created before the ``sanity_home`` volume model keeps its
agent state (``~/.gemini``, ``~/.config``, ``~/.claude``, logins, shell
history — everything outside ``./workspace``) in the ephemeral writable
layer, where any ``down`` / ``clean`` / ``--force-recreate`` destroys it.

``upgrade`` snapshots each such container, recreates it on the new
per-tag compose (which mounts a per-project ``sanity_home`` volume),
seeds that volume from the snapshot, then starts it. The snapshot image
is kept as a rollback point; the old container is removed only after its
data is safely captured. Ported from upstream commit 40483e4.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

from sanity_gravity.cli.colors import Colors
from sanity_gravity.cli.io import (
    get_uid_gid_user,
    print_error,
    print_header,
    print_info,
    print_plain,
    print_success,
    print_warning,
    run_command,
    validate_project_name,
    validate_username,
)
from sanity_gravity.compose.generators import (
    generate_compose_for_tag,
    generate_git_compose,
)
from sanity_gravity.domain.naming import Naming
from sanity_gravity.domain.tags import Tag
from sanity_gravity.verbs.lifecycle import (
    get_legacy_containers,
    get_legacy_projects,
    get_project_env,
    legacy_target_tag,
)
from sanity_gravity.verbs.up import is_port_in_use


def run_step(argv, *, capture=False, env=None):
    """Run one migration step; raise ``RuntimeError`` on failure.

    Unlike :func:`sanity_gravity.cli.io.run_command`, this never calls
    ``sys.exit`` — the caller must be able to catch a failure so a
    half-done migration can report exactly which stage stopped and how
    to recover. ``env`` is merged into ``os.environ`` for the child.
    """
    run_env = None
    if env is not None:
        run_env = os.environ.copy()
        run_env.update({k: str(v) for k, v in env.items()})
    if not capture:
        print_plain(f"{Colors.OKBLUE}$ {' '.join(str(a) for a in argv)}{Colors.ENDC}")
    r = subprocess.run(
        list(argv), capture_output=True, text=True, env=run_env,
    )
    if r.returncode != 0:
        raise RuntimeError(
            (r.stderr or r.stdout or "").strip() or f"exit {r.returncode}"
        )
    return r.stdout.strip()


def get_published_ports(container_id):
    """Recover a container's configured host port bindings as sanity env vars.

    ``upgrade`` uses this so a migrated container keeps the same
    SSH / KASM / VNC / noVNC host ports its predecessor had.

    Reads ``.HostConfig.PortBindings`` (the configured *intent*) rather
    than ``.NetworkSettings.Ports`` (the live mapping): a port the user
    left ephemeral shows here as ``"0"`` and should stay ephemeral on
    the new container, not get pinned to whatever number Docker happened
    to assign this run.

    ``get_project_env`` cannot supply these — it keys container names
    off ``VALID_TAGS`` so it never matches a legacy
    ``<project>-<core|kasm|vnc>-1`` name, and the ports were never
    compose ``environment:`` vars in the first place.

    Returns ``{ENV_VAR: "host_port"}`` for whichever connector ports are
    bound; ``{}`` if the container cannot be inspected.
    """
    cport_to_env = {
        "22/tcp": "SSH_HOST_PORT", "8444/tcp": "KASM_PORT",
        "5901/tcp": "VNC_PORT", "6901/tcp": "NOVNC_PORT",
    }
    fmt = (
        "{{range $p, $c := .HostConfig.PortBindings}}{{if $c}}"
        "{{$p}}={{(index $c 0).HostPort}} {{end}}{{end}}"
    )
    out = run_command(
        ("docker", "inspect", container_id, "--format", fmt),
        capture=True, check=False,
    )
    result = {}
    for token in (out or "").split():
        cport, _, host_port = token.partition("=")
        env_key = cport_to_env.get(cport)
        if env_key and host_port:
            result[env_key] = host_port
    return result


def _recover_env(project, cid, host_uid, host_gid, host_user):
    """Recover the runtime env for a project, filling sane defaults.

    Host ports are recovered in two passes: first from the old
    container's configured ``PortBindings`` (so the migrated container
    stays reachable on the same SSH/KASM/VNC ports — including ``"0"``
    for a port the user deliberately left ephemeral); then any port
    still unknown is set to ``0`` so Docker assigns a free one rather
    than risk a collision on recreate.
    """
    env_vars = get_project_env(project)
    env_vars.setdefault("HOST_USER", host_user)
    env_vars.setdefault("HOST_UID", str(host_uid))
    env_vars.setdefault("HOST_GID", str(host_gid))
    # Pass 1 — preserve the old container's configured bindings. This
    # runs while the old container still exists (it is removed later,
    # at step 4 of the migration).
    for env_key, host_port in get_published_ports(cid).items():
        env_vars.setdefault(env_key, host_port)
    # Pass 2 — ephemeral fallback for anything still unknown.
    for key, port in (
        ("SSH_HOST_PORT", 2222), ("KASM_PORT", 8444),
        ("VNC_PORT", 5901), ("NOVNC_PORT", 6901),
    ):
        if key not in env_vars and (
            project != "sanity-gravity" or is_port_in_use(port)
        ):
            env_vars[key] = "0"
    return env_vars


def _migrate_one(item, host_uid, host_gid, host_user, timestamp):
    """Migrate a single container. Returns on success; raises on failure.

    The raised exception carries a ``.stage`` attribute so the caller
    can tell the user whether the old container is still intact.
    """
    project, service = item["project"], item["service"]
    cid, name, tag = item["cid"], item["name"], item["tag"]
    # ``tag`` came out of legacy_target_tag, so it always parses.
    naming = Naming(Tag.parse(tag), project)
    if service == tag:
        # A managed container migrating in place: its service label
        # already is the target tag, so the rollback ref is a Naming
        # render like every other identity.
        backup_img = naming.backup_image(timestamp)
    else:
        # A genuine legacy container has a flat service name
        # (core/kasm/vnc) that is not a tag. The rollback ref must keep
        # that OLD name - it identifies what was snapshotted, and the
        # recovery hint prints it back - so only the repo prefix is
        # shared with Naming here.
        backup_img = f"{Naming.BACKUP_REPO}/{project}-{service}:{timestamp}"

    print_header(f"Migrating {name} ({service} -> {tag})")
    stage = "snapshot"
    try:
        validate_project_name(project)

        # 1. Safety snapshot. The old container is still running and is
        #    not touched until step 4 — if anything here fails it stays
        #    intact.
        print_info(f"Snapshotting -> {backup_img}")
        run_step(("docker", "commit", cid, backup_img))

        # 2. Recover environment from the old container — including its
        #    configured host port bindings (the container still exists;
        #    it is removed at step 4).
        env_vars = _recover_env(project, cid, host_uid, host_gid, host_user)
        username = validate_username(env_vars["HOST_USER"])

        # 3. Generate the new per-tag compose (+ git overlay). The tag
        #    compose declares the sanity_home volume. The git overlay is
        #    scoped to THIS tag — without a service arg generate_git_compose
        #    emits every VALID_TAG as an image-less service and
        #    `compose create` then rejects the whole project.
        tag_compose, _ = generate_compose_for_tag(tag)
        compose_flags = ["-f", tag_compose]
        git_compose = generate_git_compose(username, tag)
        if git_compose:
            compose_flags += ["-f", git_compose]

        # 4. Remove the old container. Its data is already in backup_img.
        stage = "old-removed"
        print_info("Removing old container (data preserved in snapshot)...")
        run_step(("docker", "rm", "-f", cid))

        # 5. Create (do not start) the new container so its sanity_home
        #    volume exists but is still empty.
        run_step(
            ("docker", "compose", "-p", project, *compose_flags,
             "create", "--force-recreate", tag),
            env=env_vars,
        )

        # 6. Find the named volume mounted at the home dir.
        new_name = naming.container()
        mount_fmt = (
            '{{range .Mounts}}{{if eq .Destination "/home/'
            + username
            + '"}}{{.Name}}{{end}}{{end}}'
        )
        vol = run_step(
            ("docker", "inspect", new_name, "--format", mount_fmt),
            capture=True,
        )
        if not vol:
            raise RuntimeError(f"no home volume found on {new_name}")

        # 7. Seed the volume from the snapshot — the whole home including
        #    dotfiles. workspace / .gitconfig are re-bind-mounted from the
        #    host at runtime, so their snapshot copies are moot.
        stage = "seeding"
        print_info(f"Seeding volume {vol} from snapshot...")
        run_step((
            "docker", "run", "--rm", "--entrypoint", "bash",
            "-v", f"{vol}:/dest", backup_img,
            "-lc", f"shopt -s dotglob; cp -a /home/{username}/. /dest/",
        ))

        # 8. Start it. The volume is now non-empty, so Docker will not
        #    overlay the image's /home; entrypoint chowns it.
        stage = "starting"
        run_step(
            ("docker", "compose", "-p", project, *compose_flags, "start", tag),
            env=env_vars,
        )
        if not run_step(
            ("docker", "ps", "-q", "--filter", f"name=^{new_name}$"),
            capture=True,
        ):
            raise RuntimeError(f"{new_name} did not come up")

        print_success(f"{name} migrated -> {new_name}")
        print_info(f"Rollback image kept: {backup_img}")
    except Exception as exc:  # noqa: BLE001 — caller reports + decides
        exc.stage = stage  # type: ignore[attr-defined]
        exc.backup_img = backup_img  # type: ignore[attr-defined]
        raise


def upgrade(args):
    """Losslessly migrate legacy / pre-volume containers to persistent home."""
    records = get_legacy_containers()

    target = getattr(args, "name", "sanity-gravity")
    if target != "sanity-gravity":
        records = [r for r in records if r["project"] == target]
        if not records:
            print_error(
                f"Project '{target}' has no container needing migration."
            )
            others = get_legacy_projects()
            if others:
                print_plain(f"Projects needing migration: {', '.join(others)}")
            return

    if not records:
        print_success(
            "All containers already use the persistent-home volume. "
            "Nothing to migrate."
        )
        return

    # Resolve the target tag for each container; drop unmappable ones.
    plan = []
    for r in records:
        tag = legacy_target_tag(r["service"])
        if not tag:
            print_warning(
                f"Skipping {r['name']}: cannot map service "
                f"'{r['service']}' to a known tag."
            )
            continue
        plan.append({**r, "tag": tag})
    if not plan:
        print_error("Nothing migratable.")
        return

    print_header("Lossless Migration Plan")
    print_plain(
        "Each container is snapshotted, its entire home (agent state, logins,\n"
        "history — everything outside ./workspace) copied into a new\n"
        "per-project volume, then recreated. The snapshot image is kept so\n"
        "you can roll back. The old container is removed only after its data\n"
        "is safely captured.\n"
    )
    for item in plan:
        print_plain(
            f"  {item['name']}  [{item['project']}]  "
            f"{item['service']} -> {item['tag']}"
        )
    print_plain("")

    if sys.stdin.isatty():
        choice = input(
            f"{Colors.BOLD}Proceed with lossless migration? [y/N]: {Colors.ENDC}"
        ).lower().strip()
        if choice != "y":
            print_info("Migration cancelled.")
            return
    else:
        print_warning("Non-interactive mode: auto-proceeding.")

    host_uid, host_gid, host_user = get_uid_gid_user()
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    ok, failed = [], []

    for item in plan:
        try:
            _migrate_one(item, host_uid, host_gid, host_user, timestamp)
            ok.append(item["name"])
        except Exception as exc:  # noqa: BLE001
            failed.append(item["name"])
            stage = getattr(exc, "stage", "?")
            backup_img = getattr(exc, "backup_img", "(no snapshot)")
            print_error(
                f"Migration of {item['name']} failed during '{stage}': {exc}"
            )
            if stage == "snapshot":
                print_warning(
                    "The old container was NOT touched — it is still intact. "
                    "Nothing was lost."
                )
            else:
                print_warning(
                    f"Your data is safe in image '{backup_img}'. The old "
                    f"container was already removed. To bring the old one "
                    f"back as-is:\n  docker run -d --name {item['name']} "
                    f"{backup_img}"
                )
            print_warning("Stopping here so you can inspect before continuing.")
            break

    print_header("Migration Summary")
    if ok:
        print_success(f"Migrated: {', '.join(ok)}")
    if failed:
        print_error(f"Failed/aborted: {', '.join(failed)}")
    if ok and not failed:
        print_info(
            "Verify the agents work, then sanity-migrate/* images can be "
            "deleted to reclaim space."
        )

    # Late import to avoid a circular dependency with the status module.
    from sanity_gravity.verbs.status import status
    status(args)
