"""LayerRef: the identity of one node in the build DAG.

A layer is *structure*, not a name. The only place a LayerRef becomes a
string is :meth:`sanity_gravity.domain.naming.Naming.layer`;
``Naming.parse_layer`` is its inverse, whose job is to witness the
grammar's round-trip property (a property test binds the pair) -
production strings enter as (--layer, --layer-target) selectors via
:meth:`LayerRef.of` instead. Everything in between - planning, parent
resolution, ``--layer`` filtering, cache probing - moves values.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from sanity_gravity.domain.errors import SanityError
from sanity_gravity.domain.tags import Tag


class LayerError(SanityError, ValueError):
    """Invalid layer structure or selector."""


class LayerKind(IntEnum):
    """Build depth doubles as the enum value: a parent is exactly one
    step shallower, which makes stratified plan ordering a plain sort
    on ``int(kind)``."""

    BASE = 0
    DESKTOP = 1
    AGENT = 2
    CONNECTOR = 3

    @classmethod
    def parse(cls, raw: str) -> LayerKind:
        """argv edge: the ``--layer`` value."""
        try:
            return cls[raw.upper()]
        except KeyError:
            raise LayerError(
                f"Unknown layer type: {raw}. Valid: base, desktop, agent, connector"
            ) from None

    def __str__(self) -> str:
        return self.name.lower()


#: Which structural fields each kind carries. This table IS the shape
#: contract: it drives validation, detail rendering, and --layer-target
#: parsing. Adding a dimension is one edit here.
_FIELDS: dict[LayerKind, tuple[str, ...]] = {
    LayerKind.BASE: (),
    LayerKind.DESKTOP: ("desktop",),
    LayerKind.AGENT: ("agent", "desktop"),
    LayerKind.CONNECTOR: ("agent", "desktop", "connector"),
}


@dataclass(frozen=True)
class LayerRef:
    """One node identity. Hashable, comparable, never a string."""

    kind: LayerKind
    agent: str | None = None
    desktop: str | None = None
    connector: str | None = None

    def __post_init__(self) -> None:
        required = _FIELDS[self.kind]
        for field in ("agent", "desktop", "connector"):
            present = getattr(self, field) is not None
            if present is not (field in required):
                raise LayerError(
                    f"{self.kind} layer: field {field!r} must "
                    f"{'be' if field in required else 'not be'} set"
                )

    # -- constructors: the only ways to make one -----------------------

    @classmethod
    def base(cls) -> LayerRef:
        return cls(LayerKind.BASE)

    @classmethod
    def of_desktop(cls, desktop: str) -> LayerRef:
        return cls(LayerKind.DESKTOP, desktop=desktop)

    @classmethod
    def of_agent(cls, agent: str, desktop: str) -> LayerRef:
        return cls(LayerKind.AGENT, agent=agent, desktop=desktop)

    @classmethod
    def of_tag(cls, tag: Tag) -> LayerRef:
        return cls(
            LayerKind.CONNECTOR,
            agent=tag.agent,
            desktop=tag.desktop,
            connector=tag.connector,
        )

    @classmethod
    def of(cls, kind: LayerKind, detail: str | None) -> LayerRef:
        """Inverse of :attr:`detail` - and also the (--layer,
        --layer-target) selector pair. Splitting on '-' is total
        because slugs match ^[a-z][a-z0-9]*$."""
        parts = detail.split("-") if detail else []
        fields = _FIELDS[kind]
        if len(parts) != len(fields):
            expected = "-".join(f"<{f}>" for f in fields) or "(none)"
            raise LayerError(
                f"--layer {kind} expects --layer-target {expected}, got {detail!r}"
            )
        return cls(kind, **dict(zip(fields, parts)))

    # -- projections ---------------------------------------------------

    @property
    def detail(self) -> str | None:
        """The layer-name payload; None for the base layer."""
        parts = [getattr(self, f) for f in _FIELDS[self.kind]]
        return "-".join(parts) if parts else None

    @property
    def parent(self) -> LayerRef | None:
        """The single parent rule for the whole repo."""
        match self.kind:
            case LayerKind.BASE:
                return None
            case LayerKind.DESKTOP:
                return LayerRef.base()
            case LayerKind.AGENT:
                assert self.desktop is not None
                return LayerRef.of_desktop(self.desktop)
            case LayerKind.CONNECTOR:
                assert self.agent is not None and self.desktop is not None
                return LayerRef.of_agent(self.agent, self.desktop)

    @property
    def ancestors(self) -> tuple[LayerRef, ...]:
        """Root-first chain of parents (excluding self)."""
        out: list[LayerRef] = []
        node = self.parent
        while node is not None:
            out.append(node)
            node = node.parent
        return tuple(reversed(out))

    @property
    def sort_key(self) -> tuple[int, str, str, str]:
        """Total, machine-independent order: depth, then structure.
        Depth-major guarantees parents sort before their children."""
        return (
            int(self.kind),
            self.agent or "",
            self.desktop or "",
            self.connector or "",
        )
