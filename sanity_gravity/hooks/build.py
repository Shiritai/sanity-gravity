"""Builtin hooks implementing the ``build`` lifecycle.

The build chain is ``base → desktop → agent → connector``. Each layer
is a standalone Dockerfile with ``ARG BASE_IMAGE`` / ``FROM
${BASE_IMAGE}``. Intermediate images are tagged with ``_`` prefix
(e.g. ``sanity-gravity:_base``).

Phase split:
- ``BUILD_PLAN`` — for each target, walk the chain, decide what to build
  (skip cached unless ``no_cache``), append entries to ``ctx.plan``.
- ``BUILD_LAYER`` — for each plan step, enqueue a ``RunSubprocess``
  Action invoking ``docker build``.
- ``BUILD_DONE`` — emit the success summary.
"""
from __future__ import annotations

import os
import subprocess
import sys

from sanity_gravity.cli.registry import (
    DESKTOPS,
    OFFICIAL_TAGS,
    get_registry,
    parse_tag,
)
from sanity_gravity.core.command import CommandBuilder
from sanity_gravity.core.eventbus import EventBus, get_default_bus
from sanity_gravity.domain.phase import Phase
from sanity_gravity.effects.actions import RunSubprocess


SANDBOX_DIR = "sandbox"
IMAGE_PREFIX = "sanity-gravity"


def _image_tag(name: str) -> str:
    return f"{IMAGE_PREFIX}:{name}"


def _image_exists(tag: str) -> bool:
    """Local image existence check (skipped in dry-run upstream)."""
    r = subprocess.run(
        ("docker", "image", "inspect", tag),
        capture_output=True, text=True,
    )
    return r.returncode == 0


def _plugin_dockerfile(kind: str, slug: str) -> str:
    return str(get_registry().get(kind, slug).dockerfile_path)


def _build_context_for(dockerfile_path: str) -> str:
    """Pick the docker build context for a given Dockerfile.

    - ``sandbox/Dockerfile.base`` keeps ``sandbox/`` as its context so it
      can ``COPY rootfs /``.
    - Plugin Dockerfiles use **their own directory** as the context.
    """
    df = os.path.abspath(dockerfile_path)
    base_df = os.path.abspath(os.path.join(SANDBOX_DIR, "Dockerfile.base"))
    if df == base_df:
        return SANDBOX_DIR
    return os.path.dirname(dockerfile_path)


def _get_unique_agent_desktop_pairs() -> list[tuple[str, str]]:
    # Enumeration follows the official tier: intermediates for
    # community/deprecated tags are only built when explicitly targeted.
    pairs: set[tuple[str, str]] = set()
    for tag in OFFICIAL_TAGS:
        a, d, _ = tag.split("-")
        pairs.add((a, d))
    return sorted(pairs)


def _resolve_build_chain(tag: str) -> list[tuple[str, str, str | None]]:
    """Build chain for a final tag as ``[(dockerfile, image_name, parent)]``."""
    agent, desktop, connector = parse_tag(tag)
    return [
        (os.path.join(SANDBOX_DIR, "Dockerfile.base"), "_base", None),
        (_plugin_dockerfile("desktop", desktop), f"_base-{desktop}", "_base"),
        (_plugin_dockerfile("agent", agent),
         f"_{agent}-{desktop}", f"_base-{desktop}"),
        (_plugin_dockerfile("connector", connector),
         tag, f"_{agent}-{desktop}"),
    ]


def _resolve_intermediate_chain(target: str) -> list[tuple[str, str, str | None]]:
    if target == "_base":
        return [(os.path.join(SANDBOX_DIR, "Dockerfile.base"), "_base", None)]
    if target.startswith("_base-"):
        desktop = target[len("_base-"):]
        if desktop not in get_registry().desktops:
            raise ValueError(f"Unknown intermediate target: {target}")
        return [
            (os.path.join(SANDBOX_DIR, "Dockerfile.base"), "_base", None),
            (_plugin_dockerfile("desktop", desktop), target, "_base"),
        ]
    if target.startswith("_"):
        parts = target[1:].split("-")
        if len(parts) == 2:
            agent, desktop = parts
            reg = get_registry()
            if agent in reg.agents and desktop in reg.desktops:
                return [
                    (os.path.join(SANDBOX_DIR, "Dockerfile.base"), "_base", None),
                    (_plugin_dockerfile("desktop", desktop),
                     f"_base-{desktop}", "_base"),
                    (_plugin_dockerfile("agent", agent),
                     target, f"_base-{desktop}"),
                ]
    raise ValueError(f"Unknown intermediate target: {target}")


def _generate_intermediates() -> list[str]:
    intermediates = ["_base"]
    desktops_needed: set[str] = set()
    for _, d in _get_unique_agent_desktop_pairs():
        desktops_needed.add(d)
    for d in sorted(desktops_needed):
        intermediates.append(f"_base-{d}")
    for a, d in _get_unique_agent_desktop_pairs():
        intermediates.append(f"_{a}-{d}")
    return intermediates


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------


def build_plan(ctx) -> None:
    """BUILD_PLAN/100: assemble ``ctx.plan`` from targets / layer / etc.

    Cache-skip decisions happen here, *not* during BUILD_LAYER, so the
    plan is fully knowable up front (useful for ``--dry-run`` / explain).
    """
    # ``--list-intermediates`` is a special read-only flag; the verb
    # entrypoint handles it before constructing the kernel ctx.

    no_cache = ctx.no_cache
    base_override = ctx.base_image_override

    # Layer mode: build only up to a specific layer type.
    if ctx.layer_target:
        _plan_layer(ctx, ctx.layer_target, ctx.layer_target_specific, no_cache)
        return

    # Default: build the requested final tags (or all of OFFICIAL_TAGS —
    # ``all`` is CI's build set, so it follows the official tier).
    targets = ctx.targets or []
    if "all" in targets:
        # Phase 1: intermediates.
        _plan_intermediates(ctx, no_cache)
        # Phase 2: every final image.
        for tag in OFFICIAL_TAGS:
            chain = _resolve_build_chain(tag)
            for dockerfile, image_name, parent in chain:
                if image_name == tag:
                    # Final image always builds; intermediate cache-skip
                    # already handled in _plan_intermediates.
                    ctx.plan.append((dockerfile, image_name, parent))
        return

    for target in targets:
        try:
            parse_tag(target)
        except ValueError as e:
            ctx.reporter.error(str(e))
            sys.exit(1)
        if base_override:
            agent, desktop, connector = parse_tag(target)
            dockerfile = _plugin_dockerfile("connector", connector)
            ctx.plan.append((dockerfile, target, None))  # parent=None → use override
            continue
        chain = _resolve_build_chain(target)
        for dockerfile, image_name, parent in chain:
            full_tag = _image_tag(image_name)
            # Skip cached intermediates only; final tag always rebuilds.
            if image_name != target and not no_cache:
                if not ctx.dry_run and _image_exists(full_tag):
                    ctx.reporter.info(f"  Cache hit: {full_tag}")
                    continue
            ctx.plan.append((dockerfile, image_name, parent))


def _plan_layer(ctx, layer_type: str, target: str | None, no_cache: bool) -> None:
    if layer_type == "base":
        ctx.plan.extend(_resolve_intermediate_chain("_base"))
        return
    if layer_type == "desktop":
        ctx.plan.extend(_resolve_intermediate_chain("_base"))
        desktops = [target] if target else list(DESKTOPS.keys())
        for d in desktops:
            name = f"_base-{d}"
            if not no_cache and not ctx.dry_run and _image_exists(_image_tag(name)):
                ctx.reporter.info(f"  Cache hit: {_image_tag(name)}")
                continue
            chain = _resolve_intermediate_chain(name)
            ctx.plan.append(chain[-1])
        return
    if layer_type == "agent":
        ctx.plan.extend(_resolve_intermediate_chain("_base"))
        if target:
            pairs = [tuple(target.split("-"))]
        else:
            pairs = _get_unique_agent_desktop_pairs()
        seen_desktops: set[str] = set()
        for a, d in pairs:
            if d not in seen_desktops:
                name = f"_base-{d}"
                if no_cache or ctx.dry_run or not _image_exists(_image_tag(name)):
                    ctx.plan.append(_resolve_intermediate_chain(name)[-1])
                seen_desktops.add(d)
            agent_name = f"_{a}-{d}"
            if not no_cache and not ctx.dry_run and _image_exists(_image_tag(agent_name)):
                ctx.reporter.info(f"  Cache hit: {_image_tag(agent_name)}")
                continue
            ctx.plan.append(_resolve_intermediate_chain(agent_name)[-1])
        return
    if layer_type == "connector":
        _plan_intermediates(ctx, no_cache)
        for tag in OFFICIAL_TAGS:
            chain = _resolve_build_chain(tag)
            ctx.plan.append(chain[-1])
        return
    ctx.reporter.error(
        f"Unknown layer type: {layer_type}. Valid: base, desktop, agent, connector"
    )
    sys.exit(1)


def _plan_intermediates(ctx, no_cache: bool) -> None:
    for name in _generate_intermediates():
        full_tag = _image_tag(name)
        if not no_cache and not ctx.dry_run and _image_exists(full_tag):
            ctx.reporter.info(f"  Cache hit: {full_tag}")
            continue
        chain = _resolve_intermediate_chain(name)
        ctx.plan.append(chain[-1])


def build_layers(ctx) -> None:
    """BUILD_LAYER/100: enqueue a RunSubprocess per planned step."""
    plan = ctx.plan
    total = len(plan)
    base_override = ctx.base_image_override
    for i, (dockerfile, image_name, parent) in enumerate(plan, 1):
        if not os.path.exists(dockerfile):
            ctx.reporter.error(f"Layer file not found: {dockerfile}")
            sys.exit(1)
        full_tag = _image_tag(image_name)
        layer_label = os.path.relpath(dockerfile)
        ctx.reporter.info(f"  [{i}/{total}] Building {full_tag} ({layer_label})")

        context = _build_context_for(dockerfile)
        cb = CommandBuilder("docker", "build").flag("--no-cache", when=ctx.no_cache)
        if base_override and parent is None:
            cb.opt("--build-arg", f"BASE_IMAGE={base_override}")
        elif parent is not None:
            cb.opt("--build-arg", f"BASE_IMAGE={_image_tag(parent)}")
        cb.opt("-f", dockerfile).opt("-t", full_tag).positional(context)
        ctx.actions.append(RunSubprocess(argv=cb.build()))


def build_done(ctx) -> None:
    """BUILD_DONE/100: emit success line(s)."""
    if not ctx.plan:
        ctx.reporter.info("Nothing to build (everything cached).")
        return
    targets = ctx.targets or []
    if ctx.layer_target:
        ctx.reporter.success(f"{ctx.layer_target} layer(s) built")
    elif "all" in targets:
        ctx.reporter.success("All builds complete!")
    else:
        for t in targets:
            ctx.reporter.success(f"Built {_image_tag(t)}")


def register_builtin_build_hooks(bus: EventBus) -> None:
    """Subscribe build hooks; splice in plugin-contributed hooks last."""
    from sanity_gravity.plugins.registry import default_registry
    default_registry()  # ensure plugin hooks.py modules are loaded

    bus.subscribe(Phase.BUILD_PLAN, build_plan, priority=100)
    bus.subscribe(Phase.BUILD_LAYER, build_layers, priority=100)
    bus.subscribe(Phase.BUILD_DONE, build_done, priority=100)

    get_default_bus().merge_into(bus)
