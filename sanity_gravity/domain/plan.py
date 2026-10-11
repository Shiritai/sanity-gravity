"""Build plan = topological closure over LayerRef parents.

Nothing here renders a name and nothing here talks to Docker: the
closure is pure structure, the cache probe is an injected predicate,
and the :class:`LayerBinding` arrives as a callable from the hook
layer - the only module that knows about the filesystem.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from sanity_gravity.domain.layers import LayerKind, LayerRef
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


CacheProbe = Callable[[LayerRef], bool]


def NEVER_CACHED(ref: LayerRef) -> bool:
    """--no-cache and --dry-run both mean "assume nothing is built"."""
    return False


#: Kinds rebuilt even when present locally. The final image only,
#: matching the historical "final tag always rebuilds" rule. Planner
#: policy, not request data: no call site has ever varied it.
_ALWAYS_BUILD: frozenset[LayerKind] = frozenset({LayerKind.CONNECTOR})


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
    probe: CacheProbe = NEVER_CACHED,
    on_cache_hit: Callable[[LayerRef], None] = lambda ref: None,
) -> list[PlanNode]:
    """The whole planner: one loop, one cache probe site.

    Whether cache is consulted at all is the caller's decision, made
    once by choosing ``probe`` (--no-cache / --dry-run inject
    :func:`NEVER_CACHED`); there is deliberately no second flag here
    for the same fact to drift against.
    """
    nodes: list[PlanNode] = []
    for ref in closure(roots):
        if ref.kind not in _ALWAYS_BUILD and probe(ref):
            on_cache_hit(ref)
            continue
        nodes.append(PlanNode(layer=ref, binding=bind(ref)))
    return nodes
