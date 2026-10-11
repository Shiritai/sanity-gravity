"""LayerRef: the identity of one node in the build DAG.

A layer is *structure*, not a name. The only place a LayerRef becomes a
string is :meth:`sanity_gravity.domain.naming.Naming.layer`;
``Naming.parse_layer`` is its inverse, whose job is to witness the
grammar's round-trip property (a property test binds the pair).
Production strings enter as tags, through :meth:`LayerRef.of_tag`.
Everything in between - planning, parent resolution, cache probing -
moves values.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum

from sanity_gravity.domain.errors import SanityError
from sanity_gravity.domain.tags import RESERVED_SLUGS, SLUG_RE, Tag


class LayerError(SanityError, ValueError):
    """Invalid layer structure or layer name."""


class LayerKind(IntEnum):
    """Build depth doubles as the enum value: a parent is exactly one
    step shallower, which makes stratified plan ordering a plain sort
    on ``int(kind)``."""

    BASE = 0
    DESKTOP = 1
    AGENT = 2
    CONNECTOR = 3

    def __str__(self) -> str:
        return self.name.lower()


#: The build order. A layer binds a PREFIX of it - the base alone, then
#: the desktop, then the agent, then the connector - and its name is
#: that prefix, so the number of bound slugs IS the kind. Cheap,
#: varied layers sit on top of expensive, shared ones: one agent install
#: serves three connectors. Tag order is the user's reading order and is
#: deliberately a separate thing.
_BUILD_ORDER: tuple[str, ...] = ("base", "desktop", "agent", "connector")


@dataclass(frozen=True)
class LayerRef:
    """One node identity: a bound prefix of the build order.

    Hashable, comparable, never a string. The final layer binds every
    dimension, which is exactly a Tag, so it carries the Tag itself and
    its name is rendered by the tag grammar rather than by a copy of it.
    """

    base: str
    desktop: str | None = None
    agent: str | None = None
    tag: Tag | None = None

    def __post_init__(self) -> None:
        # The prefix rule first: kind is derived from how many slots are
        # bound, and a ref with a gap would still yield a plausible kind.
        slots = (self.base, self.desktop, self.agent, self.tag)
        depth = slots.index(None) if None in slots else len(slots)
        if depth == 0 or any(v is not None for v in slots[depth:]):
            raise LayerError(
                f"a layer binds a non-empty prefix of {_BUILD_ORDER}; "
                f"got base={self.base!r}, desktop={self.desktop!r}, "
                f"agent={self.agent!r}, tag={self.tag!r}"
            )
        # Names are told apart by segment count alone, which holds only
        # while no slug contains the separator; a Tag checks its own.
        for dim, slug in zip(_BUILD_ORDER, (self.base, self.desktop, self.agent)):
            if slug is not None and (
                not SLUG_RE.fullmatch(slug) or slug in RESERVED_SLUGS
            ):
                raise LayerError(
                    f"invalid {dim} slug {slug!r}: expected [a-z][a-z0-9]*, "
                    f"not a reserved word"
                )
        t = self.tag
        if t is not None and (t.base, t.desktop, t.agent) != (
            self.base, self.desktop, self.agent,
        ):
            raise LayerError(f"tag {t} disagrees with the slots it extends")

    # -- constructors: the only ways to make one -----------------------

    @classmethod
    def of_base(cls, base: str) -> LayerRef:
        return cls(base)

    @classmethod
    def of_desktop(cls, base: str, desktop: str) -> LayerRef:
        return cls(base, desktop)

    @classmethod
    def of_agent(cls, base: str, desktop: str, agent: str) -> LayerRef:
        return cls(base, desktop, agent)

    @classmethod
    def of_tag(cls, tag: Tag) -> LayerRef:
        return cls(tag.base, tag.desktop, tag.agent, tag)

    @classmethod
    def from_bound(cls, parts: Sequence[str]) -> LayerRef:
        """Inverse of :attr:`bound` for an intermediate layer. A fully
        bound prefix is a final image, decoded by the tag grammar, so
        four parts are refused here rather than accepted."""
        if not 1 <= len(parts) < len(_BUILD_ORDER):
            raise LayerError(
                f"an intermediate layer binds 1 to {len(_BUILD_ORDER) - 1} "
                f"of {_BUILD_ORDER}, got {list(parts)}"
            )
        return cls(*parts)

    # -- projections ---------------------------------------------------

    @property
    def connector(self) -> str | None:
        return self.tag.connector if self.tag is not None else None

    @property
    def bound(self) -> tuple[str, ...]:
        """The bound slugs in build order; the last one is this layer's
        own plugin."""
        slots = (self.base, self.desktop, self.agent, self.connector)
        return tuple(v for v in slots if v is not None)

    @property
    def kind(self) -> LayerKind:
        """Derived rather than stored, so a kind that disagrees with the
        bound slots cannot be represented."""
        return LayerKind(len(self.bound) - 1)

    @property
    def parent(self) -> LayerRef | None:
        """The single parent rule for the whole repo: drop the last
        bound slug. A layer's name is therefore its parent's name plus
        one segment."""
        if self.kind is LayerKind.BASE:
            return None
        return LayerRef.from_bound(self.bound[:-1])

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
    def sort_key(self) -> tuple[int, str, str, str, str]:
        """Total, machine-independent order: depth, then the slugs in
        tag order (agent, desktop, connector, base). Depth-major
        guarantees parents sort before their children; every slot is in
        the key, so no two refs tie and a sorted set has one order."""
        return (
            int(self.kind),
            self.agent or "",
            self.desktop or "",
            self.connector or "",
            self.base,
        )
