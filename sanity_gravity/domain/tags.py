"""Tag value object for dimension-based image identifiers.

A :class:`Tag` parses ``base_image-agent-desktop-connector`` strings
(e.g. ``debian-ag-xfce-kasm``). The ``base_image`` dimension is optional
and defaults to :data:`DEFAULT_BASE_IMAGE`; tags on the default base are
rendered without the prefix (``ag-xfce-kasm``) for back-compat with
existing images / tags. Constraint validation lives in the parser
callable passed to :meth:`Tag.parse`; the dataclass itself is purely a
frozen record so it round-trips cleanly through events / JSONL streams.
"""
from __future__ import annotations

from dataclasses import dataclass


#: Default OS layer; the only base whose tag prefix is elided.
DEFAULT_BASE_IMAGE = "ubuntu"


@dataclass(frozen=True)
class Tag:
    """Parsed dimension tag (``base_image-agent-desktop-connector``).

    ``base_image`` defaults to :data:`DEFAULT_BASE_IMAGE` and is rendered
    as a prefix only when it differs from the default.
    """

    agent: str
    desktop: str
    connector: str
    base_image: str = DEFAULT_BASE_IMAGE

    @classmethod
    def parse(cls, s: str, parser=None) -> "Tag":
        """Parse ``s`` via ``parser`` (constraint-checked entry point)."""
        if parser is None:
            raise ValueError("Tag.parse requires a parser callable")
        res = parser(s)
        if len(res) == 4:
            base_image, agent, desktop, connector = res
            return cls(agent=agent, desktop=desktop, connector=connector, base_image=base_image)
        agent, desktop, connector = res
        return cls(agent=agent, desktop=desktop, connector=connector)

    def __str__(self) -> str:
        if self.base_image and self.base_image != DEFAULT_BASE_IMAGE:
            return f"{self.base_image}-{self.agent}-{self.desktop}-{self.connector}"
        return f"{self.agent}-{self.desktop}-{self.connector}"

