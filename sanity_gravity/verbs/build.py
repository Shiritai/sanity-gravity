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

from sanity_gravity.cli.io import (
    get_reporter,
    print_header,
    print_warning,
)
from sanity_gravity.core.eventbus import EventBus
from sanity_gravity.core.orchestrator import (
    _BUILD_PHASES,
    BuildContext,
    Orchestrator,
)
from sanity_gravity.core.registry import (
    DEFAULT_TAG,
    OFFICIAL_TAG_VALUES,
    OFFICIAL_TAGS,
    deprecation_warning,
    resolve_tag,
)
from sanity_gravity.domain.layers import LayerKind
from sanity_gravity.domain.naming import Naming
from sanity_gravity.domain.plan import official_layers
from sanity_gravity.effects.executor import build_default_executor
from sanity_gravity.hooks.build import register_builtin_build_hooks


def generate_intermediates():
    """Intermediate layer names of the official matrix (--list-intermediates)."""
    return [
        Naming.layer(ref.kind, ref.detail)
        for ref in official_layers(OFFICIAL_TAG_VALUES)
        if ref.kind is not LayerKind.CONNECTOR
    ]


# ---------------------------------------------------------------------------


def build(args):
    """Build the requested tag(s) by routing through the microkernel."""
    no_cache = bool(getattr(args, "no_cache", False))

    # ``--list-intermediates`` is a read-only print: don't go through the
    # kernel for it.
    if getattr(args, "list_intermediates", False):
        names = generate_intermediates()
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
        # Validate eagerly so a bad tag aborts before we set up the
        # kernel. resolve_tag raises TagError (a SanityError); the CLI
        # boundary renders it and exits 1, exactly as the old
        # print+exit pair did.
        for target in targets:
            # resolve_tag IS the boundary: keep its value rather than
            # throwing it away and re-parsing the string downstream.
            notice = deprecation_warning(resolve_tag(target))
            if notice:
                print_warning(notice)
        print_header(f"Building: {', '.join(targets)}")

    reporter = getattr(args, "reporter", None) or get_reporter()
    dry_run = bool(getattr(args, "dry_run", False))

    ctx = BuildContext(
        targets=targets,
        reporter=reporter,
        no_cache=no_cache,
        layer_target=layer,
        layer_target_specific=layer_target,
        list_intermediates=False,
        json_output=bool(getattr(args, "json_output", False)),
        dry_run=dry_run,
    )

    bus = EventBus()
    register_builtin_build_hooks(bus)

    executor = build_default_executor(reporter, dry_run=dry_run)

    # ActionFailedError is a SanityError: it flies to the boundary,
    # which exits with e.exit_code (== the action result's code).
    with Orchestrator(bus, reporter, executor=executor) as orch:
        orch.run(_BUILD_PHASES, ctx)
