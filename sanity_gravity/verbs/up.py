"""``up`` / ``run`` / ``explain up`` verbs: kernel-driven container start.

The phase loop (``up.validate`` → ``up.compose`` → ``up.port_alloc`` →
``up.docker`` → ``up.provision`` → ``up.announce``) is published by
:class:`Orchestrator` against ``_UP_PHASES``; per-phase behaviour lives
in builtin hooks registered on a fresh :class:`EventBus` for this run.
"""
from __future__ import annotations

import os
import shutil
import socket
import sys

from sanity_gravity.cli.io import (
    get_reporter,
    get_uid_gid_user,
    print_error,
    print_header,
    print_info,
    print_warning,
    run_command,
    validate_project_name,
    validate_username,
)
from sanity_gravity.cli.registry import parse_tag
from sanity_gravity.core.orchestrator import (
    Deps,
    PortRequest,
    UpContext,
    Orchestrator,
    _UP_PHASES,
)
from sanity_gravity.core.eventbus import EventBus
from sanity_gravity.hooks.up import register_builtin_up_hooks
from sanity_gravity.domain.tags import Tag
from sanity_gravity.effects.actions import ActionFailedError
from sanity_gravity.effects.executor import build_default_executor
from sanity_gravity.compose.generators import (
    generate_compose_for_tag,
    generate_git_compose,
    generate_resource_compose,
)
from sanity_gravity.verbs.check import check_prereqs
from sanity_gravity.verbs.sync import sync_config


def _validate_username_with_hint(username):
    """Wrap ``validate_username`` with the legacy ``rename your host user`` hint."""
    try:
        return validate_username(username)
    except ValueError as e:
        raise ValueError(
            f"{e}. The host username is propagated into the sandbox; "
            "rename the host user or run as a user with a compliant name."
        ) from e


def is_port_in_use(port):
    """Check if ``port`` is currently in use on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0


def up(args):
    """Start the specified tag, routed through the microkernel."""
    target = args.variant

    try:
        tag = Tag.parse(target, parser=parse_tag)
    except ValueError as e:
        print_error(str(e))
        sys.exit(1)

    if not args.skip_check:
        check_prereqs(args)

    from sanity_gravity.verbs.pull import pull
    if getattr(args, "pull", False):
        pull(args)
    elif not getattr(args, "dry_run", False):
        check_img = run_command(
            ("docker", "image", "inspect", f"sanity-gravity:{target}"),
            capture=True, check=False,
        )
        if not check_img or check_img.strip() == "[]" or "Error: No such image" in check_img:
            print_warning(f"Local image sanity-gravity:{target} not found. Auto-pulling from GHCR...")
            pull(args)

    uid, gid, username = get_uid_gid_user()
    print_header(f"Starting {target}")
    print_info(f"Mapping User: {username} (UID={uid}, GID={gid})")

    workspace_path = (
        os.path.abspath(args.workspace) if args.workspace
        else os.path.abspath("workspace")
    )
    os.makedirs(workspace_path, exist_ok=True)
    print_info(f"Using Workspace: {workspace_path}")
    print_info(f"Project Name: {args.name}")

    # Collision Detection (skip in dry run to avoid subprocess calls)
    dry_run = bool(getattr(args, "dry_run", False))
    if not dry_run:
        container_name = f"{args.name}-{target}-1"
        out = run_command(f"docker ps -a -q -f name=^{container_name}$", capture=True, check=False)
        if out and isinstance(out, str) and out.strip() != "":
            if not getattr(args, 'recreate', False):
                print_error(f"Sandbox container '{container_name}' already exists!")
                print_info("To wake it up, use 'sanity-cli start'.")
                print_info("To apply new settings and recreate it, use 'sanity-cli up --recreate'.")
                print_info("To completely destroy it, use 'sanity-cli clean'.")
                sys.exit(1)
            else:
                print_warning(f"Recreating existing sandbox '{container_name}' as requested.")

    def _explicit(flags):
        return any(f in sys.argv for f in flags)

    requested_ports = PortRequest(
        ssh=args.ssh_port,
        ssh_explicit=_explicit(["--ssh-port", "-p"]),
        kasm=args.kasm_port,
        kasm_explicit=_explicit(["--kasm-port"]),
        vnc=args.vnc_port,
        vnc_explicit=_explicit(["--vnc-port"]),
        novnc=args.novnc_port,
        novnc_explicit=_explicit(["--novnc-port"]),
    )

    deps = Deps(
        validate_username=lambda u: _validate_username_with_hint(u),
        validate_project_name=validate_project_name,
        generate_compose_for_tag=generate_compose_for_tag,
        generate_git_compose=generate_git_compose,
        generate_resource_compose=generate_resource_compose,
        sync_config=sync_config,
        is_port_in_use=is_port_in_use,
        run_command=run_command,
    )

    reporter = get_reporter()
    ctx = UpContext(
        tag=tag,
        project=args.name,
        host_user=username,
        host_uid=uid,
        host_gid=gid,
        password=args.password,
        workspace=workspace_path,
        image_override=args.image,
        requested_ports=requested_ports,
        deps=deps,
        reporter=getattr(args, "reporter", None) or reporter,
        dry_run=bool(getattr(args, "dry_run", False)),
    )
    if args.cpus:
        ctx.env["_REQ_CPUS"] = args.cpus
    if args.memory:
        ctx.env["_REQ_MEMORY"] = args.memory

    bus = EventBus()
    register_builtin_up_hooks(bus)

    dry_run = bool(getattr(args, "dry_run", False))
    executor = None
    if build_default_executor is not None:
        executor = build_default_executor(ctx.reporter, dry_run=dry_run)

    # The action log is the verb's audit trail. Using the Orchestrator
    # as a context manager guarantees flush even on unhandled
    # exceptions before the interpreter unwinds.
    try:
        with Orchestrator(bus, ctx.reporter, executor=executor) as orch:
            orch.run(_UP_PHASES, ctx)
            
            # Persist a copy of the compose file(s) for postmortem.
            if executor is not None and not dry_run and ctx.compose_files:
                try:
                    run_dir = ctx.reporter.run_dir
                    run_dir.mkdir(parents=True, exist_ok=True)
                    primary = ctx.compose_files[0]
                    if os.path.exists(primary):
                        shutil.copy2(primary, run_dir / "compose.yml")
                except OSError:
                    pass  # best-effort
    except ValueError as e:
        print_error(str(e))
        sys.exit(1)
    except ActionFailedError as e:
        if reporter is not None:
            reporter.info(f"Detailed run state at: {ctx.reporter.run_dir}")
        sys.exit(e.result.exit_code or 1)
    except SystemExit:
        raise


def explain_up(args):
    """Thin alias for ``--dry-run up``: plan the up flow without executing."""
    args.dry_run = True
    return up(args)
