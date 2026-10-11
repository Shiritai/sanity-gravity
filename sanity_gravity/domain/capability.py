"""Capability solver: tag validity from manifest-declared traits.

Every plugin manifest carries ``provides`` / ``requires`` capability
lists. A 3-tuple ``(agent, desktop, connector)`` is valid iff the union
of all ``provides`` satisfies every entry in the union of all
``requires``. A requirement may list alternatives, ``a|b``, met when
any one of them is provided (Debian's ``Depends: a | b``).

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
        Requirements no plugin satisfies, each exactly as a manifest
        spelled it (alternatives included).
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


def _satisfied(requirement: str, provided: frozenset[str]) -> bool:
    """Alternatives, not conjunction: ``a|b`` is met when ANY of them is
    provided. This is how "runs on noble or bookworm" is stated as data
    rather than as an ``if`` in the kernel."""
    return any(alt in provided for alt in requirement.split("|"))


def solve(tag: Tag, registry: PluginRegistry) -> Tag:
    """Validate ``tag`` against ``registry``; return the tag on success.

    Resolves the three plugins, unions their ``provides`` and ``requires``,
    and raises :class:`CapabilityConflictError` if any required capability
    is unprovided. Missing slugs surface as ``KeyError`` from the registry
    so they're distinguishable from capability conflicts.
    """
    a = registry.get("agent", tag.agent)
    d = registry.get("desktop", tag.desktop)
    c = registry.get("connector", tag.connector)

    provided = frozenset(p for plugin in (a, d, c) for p in plugin.provides)
    required = {r for plugin in (a, d, c) for r in plugin.requires}

    # A miss is reported as the whole requirement the manifest wrote:
    # naming one of its alternatives would read as that one being needed.
    missing = frozenset(r for r in required if not _satisfied(r, provided))
    if missing:
        raise CapabilityConflictError(tag=tag, missing=missing)
    return tag
