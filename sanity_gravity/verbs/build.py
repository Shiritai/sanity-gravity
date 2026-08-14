"""``build`` verb: kernel-driven layered Docker image build.

The phase loop ``build.plan → build.layer → build.done`` is published by
:class:`Orchestrator`; per-phase behaviour lives in :mod:`build_hooks`.

A few legacy helpers (``resolve_build_chain``, ``resolve_parent``,
``generate_intermediates``) are re-exported as thin shims so existing
tests can drive the build planner directly. The implementations live
in :mod:`sanity_gravity.hooks.build`.
"""
from __future__ import annotations

import json as _json
import sys

from sanity_gravity.cli.io import (
    get_reporter,
    print_error,
    print_header,
    print_warning,
)
from sanity_gravity.cli.registry import (
    DEFAULT_TAG,
    OFFICIAL_TAGS,
    deprecation_warning,
    parse_tag,
)
from sanity_gravity.core.eventbus import EventBus
from sanity_gravity.core.orchestrator import (
    BuildContext,
    Orchestrator,
    _BUILD_PHASES,
)
from sanity_gravity.effects.actions import ActionFailedError
from sanity_gravity.effects.executor import build_default_executor
from sanity_gravity.hooks.build import (
    _agent_layer_name,
    _generate_intermediates,
    _resolve_build_chain,
    register_builtin_build_hooks,
)


# Re-exports for legacy callers ----------------------------------------------

def resolve_build_chain(tag):  # pragma: no cover - thin shim
    return _resolve_build_chain(tag)


def resolve_parent(tag):
    base_image, agent, desktop, _ = parse_tag(tag)
    return _agent_layer_name(base_image, agent, desktop)


def generate_intermediates():
    return _generate_intermediates()


# ---------------------------------------------------------------------------


def build(args):
    """Build the requested tag(s) by routing through the microkernel."""
    no_cache = bool(getattr(args, "no_cache", False))

    # ``--list-intermediates`` is a read-only print: don't go through the
    # kernel for it.
    if getattr(args, "list_intermediates", False):
        names = _generate_intermediates()
        if getattr(args, "json_output", False):
            print(_json.dumps(names))
        else:
            for n in names:
                print(n)
        return

    layer = getattr(args, "layer", None)
    layer_target = getattr(args, "layer_target", None)
    targets = list(args.variant) if getattr(args, "variant", None) else [DEFAULT_TAG]

    if layer:
        print_header(
            f"Building layer: {layer}"
            + (f" ({layer_target})" if layer_target else "")
        )
    elif "all" in targets:
        print_header(f"Building all {len(OFFICIAL_TAGS)} images")
    else:
        # Validate eagerly so a bad tag aborts before we set up the kernel.
        for target in targets:
            try:
                parse_tag(target)
            except ValueError as e:
                print_error(str(e))
                sys.exit(1)
            # Deprecated tags warn but never block (tier policy).
            notice = deprecation_warning(target)
            if notice:
                print_warning(notice)
        print_header(f"Building: {', '.join(targets)}")

    reporter = getattr(args, "reporter", None) or get_reporter()
    dry_run = bool(getattr(args, "dry_run", False))

    ctx = BuildContext(
        targets=targets,
        reporter=reporter,
        no_cache=no_cache,
        base_image_override=getattr(args, "base_image", None),
        layer_target=layer,
        layer_target_specific=layer_target,
        list_intermediates=False,
        json_output=bool(getattr(args, "json_output", False)),
        dry_run=dry_run,
    )

    bus = EventBus()
    register_builtin_build_hooks(bus)

    executor = build_default_executor(reporter, dry_run=dry_run)

    try:
        with Orchestrator(bus, reporter, executor=executor) as orch:
            orch.run(_BUILD_PHASES, ctx)
    except ActionFailedError as e:
        sys.exit(e.result.exit_code or 1)


def explain_build(args):
    """``explain build`` alias: dry-run the plan without executing."""
    args.dry_run = True
    return build(args)
