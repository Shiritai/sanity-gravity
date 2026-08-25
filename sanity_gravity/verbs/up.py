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
    print_header,
    print_info,
    print_warning,
    validate_project_name,
    validate_username,
)
from sanity_gravity.compose.generators import (
    generate_compose_for_tag,
    generate_git_compose,
    generate_resource_compose,
)
from sanity_gravity.core.eventbus import EventBus
from sanity_gravity.core.orchestrator import (
    _UP_PHASES,
    Deps,
    Orchestrator,
    PortRequest,
    RequestedPort,
    UpContext,
)
from sanity_gravity.core.proc import capture, try_run
from sanity_gravity.core.registry import deprecation_warning, resolve_tag
from sanity_gravity.domain.errors import SanityError
from sanity_gravity.domain.naming import Naming
from sanity_gravity.effects.actions import ActionFailedError
from sanity_gravity.effects.executor import build_default_executor
from sanity_gravity.hooks.up import register_builtin_up_hooks
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
    # registry + capability gate; TagError (a SanityError) flies to the
    # CLI boundary, which renders it and exits 1 as the old print+exit
    # pair did.
    tag = resolve_tag(args.variant)
    # The parse boundary ends here: identity now flows as the Tag value
    # and every derived name is a Naming render. The raw argv string
    # must not name anything past this point.
    naming = Naming(tag, args.name)

    # Deprecated tags warn but never block (tier policy) - existing
    # sandboxes keep working, only CI/publish dropped the tag.
    notice = deprecation_warning(str(tag))
    if notice:
        print_warning(notice)

    if not args.skip_check:
        check_prereqs(args)

    def _pull_or_die():
        # Decision 2: pull() reports, this verb decides -- it emits its
        # own message and fails itself instead of pull exiting from
        # underneath it.
        from sanity_gravity.verbs.pull import pull

        report = pull(args)
        if not report.ok:
            raise SanityError(
                f"Cannot start {tag}: image pull failed for "
                f"{', '.join(report.failed)}",
                hint=f"Build it locally instead: ./sanity-cli build {tag}",
            )

    if getattr(args, "pull", False):
        _pull_or_die()
    elif not getattr(args, "dry_run", False):
        # Missing image is the domain answer here (docker image inspect
        # exits non-zero / prints "[]"), so the rc is matched.
        check_img = try_run(("docker", "image", "inspect", naming.image()))
        if not check_img.ok or not check_img.stdout or check_img.stdout == "[]":
            print_warning(f"Local image {naming.image()} not found. Auto-pulling from GHCR...")
            _pull_or_die()

    uid, gid, username = get_uid_gid_user()
    print_header(f"Starting {tag}")
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
        container_name = naming.container()
        # Argv form on purpose: nothing here needs a shell, so the name
        # cannot be re-interpreted by one. capture(): stdout is the
        # answer and a broken daemon raises instead of masquerading as
        # "no collision" only to fail later inside compose up.
        out = capture(
            ("docker", "ps", "-a", "-q", "-f", f"name=^{container_name}$"),
        )
        if out:
            if not getattr(args, 'recreate', False):
                raise SanityError(
                    f"Sandbox container '{container_name}' already exists!",
                    hint=(
                        "To wake it up, use 'sanity-cli start'.\n"
                        "To apply new settings and recreate it, use "
                        "'sanity-cli up --recreate'.\n"
                        "To completely destroy it, use 'sanity-cli clean'."
                    ),
                )
            print_warning(f"Recreating existing sandbox '{container_name}' as requested.")

    def _explicit(flags):
        return any(f in sys.argv for f in flags)

    # CLI boundary: map the parser's static ``--*-port`` flags onto the
    # runtime port slugs (``PortSpec.legacy_slug``). The kernel hooks
    # below are slug-agnostic; manifest-declared slugs without a CLI
    # flag are allocated from their manifest defaults.
    requested_ports = PortRequest(entries={
        "ssh": RequestedPort(args.ssh_port, _explicit(["--ssh-port", "-p"])),
        "kasm": RequestedPort(args.kasm_port, _explicit(["--kasm-port"])),
        "vnc": RequestedPort(args.vnc_port, _explicit(["--vnc-port"])),
        "novnc": RequestedPort(args.novnc_port, _explicit(["--novnc-port"])),
    })

    deps = Deps(
        validate_username=lambda u: _validate_username_with_hint(u),
        validate_project_name=validate_project_name,
        generate_compose_for_tag=generate_compose_for_tag,
        generate_git_compose=generate_git_compose,
        generate_resource_compose=generate_resource_compose,
        sync_config=sync_config,
        is_port_in_use=is_port_in_use,
        try_run=try_run,
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
    except ActionFailedError:
        # Point at the audit trail, then let the SanityError fly to the
        # boundary (exit code == the action result's code, unchanged).
        if reporter is not None:
            reporter.info(f"Detailed run state at: {ctx.reporter.run_dir}")
        raise
    except ValueError as e:
        # ManifestError & friends are already SanityError; a bare
        # ValueError (Deps validators inside the phase run) is an
        # expected user error, so wrap it rather than let it traceback.
        if isinstance(e, SanityError):
            raise
        raise SanityError(str(e)) from e
