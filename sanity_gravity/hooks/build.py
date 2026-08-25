"""Builtin hooks implementing the ``build`` lifecycle.

The build chain is ``base -> desktop -> agent -> connector``; each
layer is a standalone Dockerfile with ``ARG BASE_IMAGE`` / ``FROM
${BASE_IMAGE}``. Planning is a topological closure over
:class:`~sanity_gravity.domain.layers.LayerRef` parents
(:mod:`sanity_gravity.domain.plan`); this module contributes only the
two edges the pure planner cannot own - binding a layer to its
(dockerfile, context) on the filesystem, and probing the local docker
image store - plus the rendering of names at the ``docker`` argv edge
via :class:`~sanity_gravity.domain.naming.Naming`.

Phase split:
- ``BUILD_PLAN`` - resolve the request to LayerRef roots, close over
  parents, apply the cache probe once, fill ``ctx.plan``.
- ``BUILD_LAYER`` - for each plan node, enqueue a ``RunSubprocess``
  Action invoking ``docker build``.
- ``BUILD_DONE`` - emit the success summary.
"""
from __future__ import annotations

import os

from sanity_gravity.core.command import CommandBuilder
from sanity_gravity.core.eventbus import EventBus, get_default_bus
from sanity_gravity.core.proc import try_run
from sanity_gravity.core.registry import (
    OFFICIAL_TAGS,
    get_registry,
    resolve_tag,
)
from sanity_gravity.domain.errors import SanityError
from sanity_gravity.domain.layers import LayerError, LayerKind, LayerRef
from sanity_gravity.domain.naming import Naming
from sanity_gravity.domain.phase import Phase
from sanity_gravity.domain.plan import (
    NEVER_CACHED,
    official_layers,
    plan,
    roots_for,
)
from sanity_gravity.domain.tags import Tag
from sanity_gravity.effects.actions import RunSubprocess

SANDBOX_DIR = "sandbox"
# The single Dockerfile.base literal: every base-layer build binds
# through this constant. It disappears once the base becomes a plugin
# and the planner reads the path from a manifest like any other layer.
BASE_DOCKERFILE = os.path.join(SANDBOX_DIR, "Dockerfile.base")


def _image_exists(tag: str) -> bool:
    """Local image existence check (skipped in dry-run upstream)."""
    return try_run(("docker", "image", "inspect", tag)).ok


def _docker_probe(ref: LayerRef) -> bool:
    return _image_exists(Naming.layer_image(ref))


_PLUGIN_KIND: dict[LayerKind, str] = {
    LayerKind.DESKTOP: "desktop",
    LayerKind.AGENT: "agent",
    LayerKind.CONNECTOR: "connector",
}


def _bind(ref: LayerRef) -> tuple[str, str]:
    """Resolve a layer to (dockerfile, build context).

    The base layer keeps ``sandbox/`` as its context so it can
    ``COPY rootfs /``; every plugin layer builds from its own
    directory. Answering "is this the base?" is now a kind check, not a
    path-string comparison.
    """
    if ref.kind is LayerKind.BASE:
        return BASE_DOCKERFILE, SANDBOX_DIR
    slug = {
        LayerKind.DESKTOP: ref.desktop,
        LayerKind.AGENT: ref.agent,
        LayerKind.CONNECTOR: ref.connector,
    }[ref.kind]
    assert slug is not None  # field occupancy guaranteed by LayerRef
    try:
        manifest = get_registry().get(_PLUGIN_KIND[ref.kind], slug)
    except KeyError:
        raise LayerError(
            f"Unknown intermediate target: {Naming.layer(ref.kind, ref.detail)}"
        ) from None
    return str(manifest.dockerfile_path), str(manifest.dir)


def _official_tags() -> list[Tag]:
    # Reads the module attribute (not the import site) so tests may
    # monkeypatch build_hooks.OFFICIAL_TAGS to shrink the matrix.
    return [Tag.parse(t) for t in OFFICIAL_TAGS]


def _roots(ctx) -> list[LayerRef]:
    """argv edge: ctx's raw strings become LayerRef roots exactly once."""
    if ctx.layer_target:
        kind = LayerKind.parse(ctx.layer_target)
        return roots_for(
            tags=(),
            layer_kind=kind,
            layer_target=ctx.layer_target_specific,
            official_tags=_official_tags(),
        )

    targets = ctx.targets or []
    if "all" in targets:
        return roots_for(
            tags=(),
            layer_kind=LayerKind.CONNECTOR,
            layer_target=None,
            official_tags=_official_tags(),
        )

    tags: list[Tag] = []
    for target in targets:
        tags.append(resolve_tag(target))  # registry + capability gate
    return roots_for(
        tags=tags, layer_kind=None, layer_target=None, official_tags=(),
    )


def build_plan(ctx) -> None:
    """BUILD_PLAN/100: ctx.plan = the closure of what was asked for.

    A bad request surfaces as LayerError / TagError from _roots -- both
    SanityError, rendered once at the CLI boundary (exit 1 unchanged).
    """
    roots = _roots(ctx)

    use_probe = not ctx.no_cache and not ctx.dry_run
    ctx.plan = plan(
        tuple(roots),
        bind=_bind,
        probe=_docker_probe if use_probe else NEVER_CACHED,
        on_cache_hit=lambda ref: ctx.reporter.info(
            f"  Cache hit: {Naming.layer_image(ref)}"
        ),
    )


def build_layers(ctx) -> None:
    """BUILD_LAYER/100: enqueue a RunSubprocess per plan node.

    The only place a layer identity is rendered to strings: image names
    come from Naming at the ``docker`` argv edge, and the parent
    reference is structure until this very line.
    """
    total = len(ctx.plan)
    for i, node in enumerate(ctx.plan, 1):
        if not os.path.exists(node.dockerfile):
            raise SanityError(f"Layer file not found: {node.dockerfile}")
        image = Naming.layer_image(node.layer)
        layer_label = os.path.relpath(node.dockerfile)
        ctx.reporter.info(f"  [{i}/{total}] Building {image} ({layer_label})")

        cb = CommandBuilder("docker", "build").flag("--no-cache", when=ctx.no_cache)
        if node.parent is not None:
            cb.opt("--build-arg", f"BASE_IMAGE={Naming.layer_image(node.parent)}")
        cb.opt("-f", node.dockerfile).opt("-t", image).positional(node.context)
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
            ctx.reporter.success(f"Built {Naming(Tag.parse(t)).image()}")


def register_builtin_build_hooks(bus: EventBus) -> None:
    """Subscribe build hooks; splice in plugin-contributed hooks last."""
    from sanity_gravity.plugins.registry import default_registry
    default_registry()  # ensure plugin hooks.py modules are loaded

    bus.subscribe(Phase.BUILD_PLAN, build_plan, priority=100)
    bus.subscribe(Phase.BUILD_LAYER, build_layers, priority=100)
    bus.subscribe(Phase.BUILD_DONE, build_done, priority=100)

    get_default_bus().merge_into(bus)


__all__ = [
    "build_plan",
    "build_layers",
    "build_done",
    "official_layers",
    "register_builtin_build_hooks",
]
