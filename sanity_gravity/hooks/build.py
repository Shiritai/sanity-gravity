"""Builtin hooks implementing the ``build`` lifecycle.

The build chain is ``base → desktop → agent → connector``. Each layer
is a standalone Dockerfile with ``ARG BASE_IMAGE`` / ``FROM
${BASE_IMAGE}``. Intermediate images are tagged with ``_`` prefix.

Intermediate naming is base-aware; the default base keeps its legacy
unprefixed names so existing ``--layer`` flows / tests stay stable:

- default base:  ``_base``, ``_base-{desktop}``, ``_{agent}-{desktop}``
- other bases:   ``_{base}_base``, ``_{base}_base-{desktop}``,
  ``_{base}_{agent}-{desktop}``

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
    OFFICIAL_TAGS,
    get_registry,
    parse_tag,
)
from sanity_gravity.core.command import CommandBuilder
from sanity_gravity.core.eventbus import EventBus, get_default_bus
from sanity_gravity.domain.phase import Phase
from sanity_gravity.domain.tags import DEFAULT_BASE_IMAGE
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


def _base_dockerfile(base_image: str) -> str:
    """Dockerfile for a base image: the plugin's when registered, else
    the default (ubuntu) base plugin — ubuntu stays the fallback image
    for unregistered overrides."""
    if base_image in get_registry().base_images:
        return _plugin_dockerfile("base-image", base_image)
    return _plugin_dockerfile("base-image", DEFAULT_BASE_IMAGE)


def _build_context_for(dockerfile_path: str) -> str:
    """Pick the docker build context for a given Dockerfile.

    Base-image Dockerfiles ``COPY rootfs /`` from the shared
    ``sandbox/`` tree, so every registered base image builds with
    ``sandbox/`` as its context. Every other plugin Dockerfile uses its
    own directory as the context.
    """
    df = os.path.abspath(dockerfile_path)
    for manifest in get_registry().base_images.values():
        if df == os.path.abspath(manifest.dockerfile_path):
            return SANDBOX_DIR
    return os.path.dirname(dockerfile_path)


def _base_layer_name(base_image: str) -> str:
    if base_image == DEFAULT_BASE_IMAGE:
        return "_base"
    return f"_{base_image}_base"


def _desktop_layer_name(base_image: str, desktop: str) -> str:
    if base_image == DEFAULT_BASE_IMAGE:
        return f"_base-{desktop}"
    return f"_{base_image}_base-{desktop}"


def _agent_layer_name(base_image: str, agent: str, desktop: str) -> str:
    if base_image == DEFAULT_BASE_IMAGE:
        return f"_{agent}-{desktop}"
    return f"_{base_image}_{agent}-{desktop}"


def _get_unique_intermediate_parts() -> list[tuple[str, str, str]]:
    # ``(base_image, agent, desktop)`` triples seen in the official tier.
    # Enumeration follows the official tier: intermediates for
    # community/deprecated tags are only built when explicitly targeted.
    parts: set[tuple[str, str, str]] = set()
    for tag in OFFICIAL_TAGS:
        b, a, d, _ = parse_tag(tag)
        parts.add((b, a, d))
    return sorted(parts)


def _resolve_build_chain(tag: str) -> list[tuple[str, str, str | None]]:
    """Build chain for a final tag as ``[(dockerfile, image_name, parent)]``."""
    base_image, agent, desktop, connector = parse_tag(tag)
    return [
        (_base_dockerfile(base_image), _base_layer_name(base_image), None),
        (_plugin_dockerfile("desktop", desktop),
         _desktop_layer_name(base_image, desktop),
         _base_layer_name(base_image)),
        (_plugin_dockerfile("agent", agent),
         _agent_layer_name(base_image, agent, desktop),
         _desktop_layer_name(base_image, desktop)),
        (_plugin_dockerfile("connector", connector),
         tag, _agent_layer_name(base_image, agent, desktop)),
    ]


def _parse_intermediate(target: str) -> tuple[str, str, str | None] | None:
    """Split an intermediate target into ``(base_image, kind, detail)``.

    Returns ``None`` when the shape isn't a known intermediate. Kind is
    ``base`` / ``desktop`` / ``agent``; ``detail`` is the desktop slug for
    desktop layers and the ``agent-desktop`` pair for agent layers.
    """
    if not target.startswith("_"):
        return None
    body = target[1:]
    if "_" in body:
        base_image, rest = body.split("_", 1)
        if base_image not in get_registry().base_images:
            return None
        body = rest
    else:
        base_image = DEFAULT_BASE_IMAGE
    if body == "base":
        return base_image, "base", None
    if body.startswith("base-"):
        return base_image, "desktop", body[len("base-"):]
    if "-" in body:
        return base_image, "agent", body
    return None


def _resolve_intermediate_chain(target: str) -> list[tuple[str, str, str | None]]:
    parsed = _parse_intermediate(target)
    if parsed is None:
        raise ValueError(f"Unknown intermediate target: {target}")
    base_image, kind, detail = parsed
    reg = get_registry()
    if kind == "base":
        return [(_base_dockerfile(base_image), target, None)]
    if kind == "desktop":
        if detail not in reg.desktops:
            raise ValueError(f"Unknown intermediate target: {target}")
        return [
            (_base_dockerfile(base_image), _base_layer_name(base_image), None),
            (_plugin_dockerfile("desktop", detail), target, _base_layer_name(base_image)),
        ]
    # kind == "agent": detail is ``agent-desktop``
    agent, desktop = detail.split("-", 1)
    if agent not in reg.agents or desktop not in reg.desktops:
        raise ValueError(f"Unknown intermediate target: {target}")
    return [
        (_base_dockerfile(base_image), _base_layer_name(base_image), None),
        (_plugin_dockerfile("desktop", desktop),
         _desktop_layer_name(base_image, desktop), _base_layer_name(base_image)),
        (_plugin_dockerfile("agent", agent), target, _desktop_layer_name(base_image, desktop)),
    ]


def _generate_intermediates() -> list[str]:
    out: list[str] = []
    parts = _get_unique_intermediate_parts()
    for b, _, _ in parts:
        if _base_layer_name(b) not in out:
            out.append(_base_layer_name(b))
    for _, _, d in parts:
        name = _desktop_layer_name(DEFAULT_BASE_IMAGE, d)
        if name not in out:
            out.append(name)
    for b, _, d in parts:
        if b != DEFAULT_BASE_IMAGE:
            name = _desktop_layer_name(b, d)
            if name not in out:
                out.append(name)
    for b, a, d in parts:
        name = _agent_layer_name(b, a, d)
        if name not in out:
            out.append(name)
    return out


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

    # Default: build the requested final tags (or all of OFFICIAL_TAGS -
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
            _, _, _, connector = parse_tag(target)
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


def _bases_in_official() -> list[str]:
    return sorted({b for b, _, _ in _get_unique_intermediate_parts()})


def _parse_layer_agent_target(target: str) -> list[tuple[str, str, str]]:
    """Resolve a ``--layer agent`` target to ``(base, agent, desktop)``.

    Accepts ``agent-desktop`` (default base), ``base-image-agent-desktop``
    and full ``{base-image-}agent-desktop-connector`` tags.
    """
    parts = target.split("-")
    if len(parts) == 2:
        return [(DEFAULT_BASE_IMAGE, *parts)]
    if len(parts) == 3 and parts[0] in get_registry().base_images:
        return [(parts[0], parts[1], parts[2])]
    try:
        b, a, d, _ = parse_tag(target)
        return [(b, a, d)]
    except ValueError:
        raise ValueError(
            f"Unknown agent layer target: {target}. "
            "Expected agent-desktop (e.g. ag-xfce) or base-agent-desktop "
            "(e.g. debian-ag-xfce)"
        ) from None


def _plan_layer(ctx, layer_type: str, target: str | None, no_cache: bool) -> None:
    if layer_type == "base":
        if target:
            if target not in get_registry().base_images:
                ctx.reporter.error(
                    f"Unknown base image: {target}. "
                    f"Valid: {', '.join(get_registry().base_images.keys())}"
                )
                sys.exit(1)
            ctx.plan.extend(_resolve_intermediate_chain(_base_layer_name(target)))
        else:
            ctx.plan.extend(_resolve_intermediate_chain("_base"))
        return
    if layer_type == "desktop":
        # Base layers first so every desktop layer has a parent.
        for b in _bases_in_official():
            ctx.plan.extend(_resolve_intermediate_chain(_base_layer_name(b)))
        # Enumeration follows the official tier like the agent /
        # connector branches: only desktops referenced by official tags
        # are built by default; other tiers still build when explicitly
        # targeted.
        if target:
            desktops = [target]
        else:
            desktops = sorted({d for _, _, d in _get_unique_intermediate_parts()})
        for d in desktops:
            for b in _bases_in_official():
                name = _desktop_layer_name(b, d)
                if not no_cache and not ctx.dry_run and _image_exists(_image_tag(name)):
                    ctx.reporter.info(f"  Cache hit: {_image_tag(name)}")
                    continue
                chain = _resolve_intermediate_chain(name)
                ctx.plan.append(chain[-1])
        return
    if layer_type == "agent":
        # Base layers first so every agent layer has a parent.
        for b in _bases_in_official():
            ctx.plan.extend(_resolve_intermediate_chain(_base_layer_name(b)))
        if target:
            parts = _parse_layer_agent_target(target)
        else:
            parts = _get_unique_intermediate_parts()
        seen_desktops: set[tuple[str, str]] = set()
        for b, a, d in parts:
            if (b, d) not in seen_desktops:
                name = _desktop_layer_name(b, d)
                if no_cache or ctx.dry_run or not _image_exists(_image_tag(name)):
                    ctx.plan.append(_resolve_intermediate_chain(name)[-1])
                seen_desktops.add((b, d))
            agent_name = _agent_layer_name(b, a, d)
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
