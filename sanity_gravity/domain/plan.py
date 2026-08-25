"""Build plan = topological closure over LayerRef parents.

Nothing here renders a name and nothing here talks to Docker: the
closure is pure structure, the cache probe is an injected predicate,
and the (dockerfile, context) binding arrives as a callable from the
hook layer - the only module that knows about the filesystem.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from sanity_gravity.domain.layers import LayerError, LayerKind, LayerRef
from sanity_gravity.domain.tags import Tag


@dataclass(frozen=True)
class PlanNode:
    """One planned ``docker build``. ``parent`` is structure, so nothing
    downstream ever re-derives it from a rendered name."""

    layer: LayerRef
    dockerfile: str
    context: str

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


def official_layers(
    official_tags: Iterable[Tag], kind: LayerKind | None = None
) -> list[LayerRef]:
    """The closure of the official matrix, optionally filtered by kind.

    Every official-matrix enumeration goes through this one closure, so
    a kind filter can never disagree with the full walk it filters."""
    layers = closure([LayerRef.of_tag(t) for t in official_tags])
    return [ref for ref in layers if kind is None or ref.kind is kind]


def roots_for(
    *,
    tags: Sequence[Tag],
    layer_kind: LayerKind | None,
    layer_target: str | None,
    official_tags: Sequence[Tag],
) -> list[LayerRef]:
    """The four historical --layer branches, as one filter.

    - no --layer            -> the requested final tags
    - --layer K --target D  -> exactly that layer (works for any
      registered slug, official or not - explicit selection has always
      ignored tiers)
    - --layer K             -> every layer of kind K in the official
      closure

    The connector kind takes no target: a fully specified connector
    layer IS a final tag, which the plain tag form already expresses.
    Passing one raises :class:`LayerError` rather than silently
    enumerating the official closure with the target ignored.
    """
    if layer_kind is None:
        return [LayerRef.of_tag(t) for t in tags]
    if layer_target is not None:
        if layer_kind is LayerKind.CONNECTOR:
            raise LayerError(
                "--layer connector takes no --layer-target: a fully "
                "specified connector layer is a final image - request "
                f"the plain tag instead (e.g. 'ag-xfce-{layer_target}')"
            )
        return [LayerRef.of(layer_kind, layer_target)]
    return official_layers(official_tags, kind=layer_kind)


def plan(
    roots: Sequence[LayerRef],
    *,
    bind: Callable[[LayerRef], tuple[str, str]],
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
        dockerfile, context = bind(ref)
        nodes.append(PlanNode(layer=ref, dockerfile=dockerfile, context=context))
    return nodes
