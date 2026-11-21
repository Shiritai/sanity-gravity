"""Build plan = topological closure over LayerRef parents.

Nothing here renders a name and nothing here talks to Docker: the
closure is pure structure, and the :class:`LayerBinding` arrives as a
callable from the hook layer - the only module that knows about the
filesystem.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from sanity_gravity.domain.layers import LayerRef
from sanity_gravity.domain.tags import Tag


@dataclass(frozen=True)
class LayerBinding:
    """Where a layer's Dockerfile and build context are. A root layer
    has no parent to build FROM, so it also carries ``from_image``; a
    non-root layer leaves it None."""

    dockerfile: str
    context: str
    from_image: str | None = None


@dataclass(frozen=True)
class PlanNode:
    """One planned ``docker build``. ``parent`` is structure, so nothing
    downstream ever re-derives it from a rendered name."""

    layer: LayerRef
    binding: LayerBinding

    @property
    def parent(self) -> LayerRef | None:
        # Delegated, not stored: one source of truth means "the parent
        # of this node" and "the parent used for --build-arg" cannot
        # drift apart.
        return self.layer.parent


def closure(roots: Sequence[LayerRef]) -> list[LayerRef]:
    """Every root plus all of its ancestors, deduped, parents first.

    Deterministic by construction: sorted by ``sort_key`` (depth, then
    structural fields), which is total and machine independent.
    Depth-major ordering guarantees a parent precedes its children.
    """
    seen: set[LayerRef] = set()
    for root in roots:
        seen.add(root)
        seen.update(root.ancestors)
    return sorted(seen, key=lambda ref: ref.sort_key)


def official_layers(official_tags: Iterable[Tag]) -> list[LayerRef]:
    """The closure of the official matrix.

    Every official-matrix enumeration goes through this one closure, so
    no caller can enumerate a subset that disagrees with the full walk.
    """
    return closure([LayerRef.of_tag(t) for t in official_tags])


def plan(
    roots: Sequence[LayerRef],
    *,
    bind: Callable[[LayerRef], LayerBinding],
) -> list[PlanNode]:
    """Every layer in the closure, each bound to its build inputs.

    No layer is skipped because its image already exists: an image
    name says nothing about whether its Dockerfile or context changed
    since it was built. Docker's layer cache compares the inputs, so
    every layer goes to ``docker build`` and an unchanged one costs
    only a cache lookup.
    """
    return [PlanNode(layer=ref, binding=bind(ref)) for ref in closure(roots)]
