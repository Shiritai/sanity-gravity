"""Capability solver: tag validity from manifest-declared traits.

Every plugin manifest carries ``provides`` / ``requires`` capability
lists. A 3-tuple ``(agent, desktop, connector)`` is valid iff the union
of all ``provides`` covers the union of all ``requires``.

This replaces the legacy hardcoded boolean rules
(``connector.requires_gui`` ↔ ``desktop.has_gui``) with a pure set
operation: adding a new capability (e.g. ``gpu``, ``audio``) does not
require touching the kernel.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sanity_gravity.domain.tags import Tag

if TYPE_CHECKING:  # pragma: no cover - type-only
    from sanity_gravity.plugins.registry import PluginRegistry


__all__ = ["CapabilityConflictError", "solve"]


@dataclass
class CapabilityConflictError(ValueError):
    """Raised when a tag's plugins fail to provide all required capabilities.

    Attributes
    ----------
    tag:
        The 3-tuple under inspection.
    missing:
        Sorted set of capability strings required but not provided.
    """

    tag: Tag
    missing: frozenset[str]

    def __post_init__(self) -> None:
        # Format a stable, helpful message even when caught and stringified.
        missing_str = ", ".join(sorted(self.missing))
        super().__init__(
            f"Tag '{self.tag}' is missing required capabilities: {missing_str}"
        )

    def __str__(self) -> str:  # pragma: no cover - thin wrapper
        return self.args[0] if self.args else super().__str__()


def solve(tag: Tag, registry: "PluginRegistry") -> Tag:
    """Validate ``tag`` against ``registry``; return the tag on success.

    Resolves the four plugins (base-image, agent, desktop, connector),
    unions their ``provides`` and ``requires``, and raises
    :class:`CapabilityConflictError` if any required capability is
    unprovided. The base-image plugin is only resolved when it is
    registered (tags default to :data:`DEFAULT_BASE_IMAGE`, which may be
    absent from synthetic registries). Missing slugs surface as
    ``KeyError`` from the registry so they're distinguishable from
    capability conflicts.
    """
    a = registry.get("agent", tag.agent)
    d = registry.get("desktop", tag.desktop)
    c = registry.get("connector", tag.connector)

    plugins = [a, d, c]
    if tag.base_image in registry.base_images:
        plugins.append(registry.get("base-image", tag.base_image))

    provided: set[str] = set()
    required: set[str] = set()
    for plugin in plugins:
        provided.update(plugin.provides)
        required.update(plugin.requires)

    missing = required - provided
    if missing:
        raise CapabilityConflictError(tag=tag, missing=frozenset(missing))
    return tag
