"""Tag value object: the identity of one logical sandbox.

This type owns the tag *grammar* and nothing else: ``parse`` and
``__str__`` are mutually inverse over well-formed values (a property
test binds the pair). Constraint validation - does this agent exist, is
the combination capability-satisfiable - is a different question and
lives in :mod:`sanity_gravity.cli.registry`, which takes and returns
values of this type.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SEP = "-"

#: Slug alphabet. '-' is the tag separator and '_' prefixes layer
#: names, so neither may appear inside a slug or the grammars stop
#: round-tripping. Mirrored by the manifest loader's _SLUG_RE.
SLUG_RE = re.compile(r"^[a-z][a-z0-9]*$")

#: The layer grammar renders desktop layers as ``_base-<desktop>`` and
#: agent layers as ``_<agent>-<desktop>``: an agent slug of ``base``
#: would make those renderings collide. Reserved across all dimensions
#: rather than just the agent one - simpler rule, zero real cost.
RESERVED_SLUGS = frozenset({"base"})


class TagError(ValueError):
    """Malformed tag string: wrong arity, bad slug alphabet, or a
    reserved slug. Subclasses ValueError so existing ``except
    ValueError`` call sites keep working during the migration."""


@dataclass(frozen=True)
class Tag:
    """Parsed dimension tag (``agent``-``desktop``-``connector``)."""

    agent: str
    desktop: str
    connector: str

    def __post_init__(self) -> None:
        # Enforced at construction, not just at parse: every Tag in the
        # process round-trips, however it was built.
        for dim, slug in (
            ("agent", self.agent),
            ("desktop", self.desktop),
            ("connector", self.connector),
        ):
            if not SLUG_RE.match(slug):
                raise TagError(
                    f"invalid {dim} slug {slug!r}: expected [a-z][a-z0-9]*"
                )
            if slug in RESERVED_SLUGS:
                raise TagError(
                    f"{dim} slug {slug!r} is reserved by the layer-name grammar"
                )

    @classmethod
    def parse(cls, s: str) -> "Tag":
        """Parse ``agent-desktop-connector``. Pure grammar; no registry."""
        parts = s.split(SEP)
        if len(parts) != 3:
            raise TagError(
                f"Invalid tag format '{s}'. Expected "
                "{agent}-{desktop}-{connector} (e.g. ag-xfce-kasm)"
            )
        return cls(agent=parts[0], desktop=parts[1], connector=parts[2])

    def __str__(self) -> str:
        return f"{self.agent}{SEP}{self.desktop}{SEP}{self.connector}"
