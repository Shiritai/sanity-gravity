"""Tag value object: the identity of one logical sandbox.

This type owns the tag *grammar* and nothing else: ``str`` renders the
canonical form and ``parse`` inverts it, ``parse(str(t)) == t`` for
every value (a property test binds the pair). Constraint validation -
does this agent exist, is the combination capability-satisfiable - is
a different question and lives in :mod:`sanity_gravity.core.registry`,
which takes and returns values of this type.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sanity_gravity.domain.errors import SanityError

SEP = "-"

#: Slug alphabet. '-' is the tag separator and '_' prefixes layer
#: names, so neither may appear inside a slug or the grammars stop
#: round-tripping. '.' is reserved for an in-segment version qualifier.
#: Used with fullmatch, since '$' alone also matches before a trailing
#: newline. Mirrored by the manifest loader's _SLUG_RE.
SLUG_RE = re.compile(r"^[a-z][a-z0-9]*$")

#: ``base`` is the name of a tag dimension, so a member called ``base``
#: (an agent in ``base-xfce-kasm``, a base in ``cc-none-ssh-base``)
#: reads as the dimension instead of a value. Naming hygiene only: no
#: grammar depends on it, since layer names are told apart by segment
#: count. Reserved across all dimensions - simpler rule, zero real cost.
RESERVED_SLUGS = frozenset({"base"})

#: The base a three-segment tag means. A grammar constant rather than
#: registry state: ``parse`` stays total, and ``str``/``parse`` stay
#: inverse, without a lookup. The base-image plugin marked
#: ``[plugin].default = true`` states the same slug as data, and the
#: plugin registry refuses a tree whose default is any other slug.
DEFAULT_BASE = "ubuntu"


class TagError(SanityError, ValueError):
    """Malformed tag string: wrong arity, bad slug alphabet, or a
    reserved slug. Under the SanityError root so the CLI boundary
    renders it; ValueError stays in the MRO so existing ``except
    ValueError`` call sites keep working during the migration."""


@dataclass(frozen=True)
class Tag:
    """Parsed dimension tag (``agent-desktop-connector[-base]``)."""

    agent: str
    desktop: str
    connector: str
    base: str = DEFAULT_BASE

    def __post_init__(self) -> None:
        # Enforced at construction, not just at parse: every Tag in the
        # process round-trips, however it was built.
        for dim, slug in (
            ("agent", self.agent),
            ("desktop", self.desktop),
            ("connector", self.connector),
            ("base", self.base),
        ):
            if not SLUG_RE.fullmatch(slug):
                raise TagError(
                    f"invalid {dim} slug {slug!r}: expected [a-z][a-z0-9]*"
                )
            if slug in RESERVED_SLUGS:
                raise TagError(
                    f"{dim} slug {slug!r} is reserved: it names a tag dimension"
                )

    @classmethod
    def parse(cls, s: str) -> Tag:
        """Parse ``agent-desktop-connector[-base]``. Pure grammar; no registry.

        The segment count alone decides the shape: three segments elide
        the base, four spell it out last. Nothing here consults a
        registry, so registering a base cannot change how a string
        parses.
        """
        parts = s.split(SEP)
        if len(parts) not in (3, 4):
            raise TagError(
                f"Invalid tag format '{s}'. Expected "
                "{agent}-{desktop}-{connector}[-{base}] (e.g. ag-xfce-kasm)"
            )
        return cls(*parts)

    def __str__(self) -> str:
        """The canonical form: the default base is always elided, so a
        default-base tag renders as its three-segment string."""
        base = "" if self.base == DEFAULT_BASE else f"{SEP}{self.base}"
        return f"{self.agent}{SEP}{self.desktop}{SEP}{self.connector}{base}"
