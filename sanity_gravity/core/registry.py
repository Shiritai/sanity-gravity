"""Lazy plugin registry + legacy dimension projections + tag parser.

The legacy ``AGENTS`` / ``CONNECTORS`` / ``DESKTOPS`` dicts are derived
from the manifest-driven registry and exposed here for back-compat with
tests and verbs that grew up reading them. ``resolve_tag`` performs
constraint validation via the capability solver, mapping the technical
"missing capability" error back to the user-friendly
"requires a GUI desktop" phrasing.
"""
from __future__ import annotations

import os
from collections.abc import Collection

from sanity_gravity.domain.capability import CapabilityConflictError
from sanity_gravity.domain.capability import solve as _capability_solve
from sanity_gravity.domain.tags import Tag, TagError
from sanity_gravity.plugins.registry import default_registry as _default_registry

PLUGINS_DIR = "plugins"
DEFAULT_TAG = "ag-xfce-kasm"


def _repo_root() -> str:
    """Return the repository root (3 dirs up from this file).

    This file lives at ``<repo>/sanity_gravity/core/registry.py``.
    """
    return os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )


def get_registry():
    """Lazy accessor: load manifests from ``plugins/`` once per process."""
    return _default_registry(os.path.join(_repo_root(), PLUGINS_DIR))


def _legacy_dim_dicts(reg):
    """Project the registry into the legacy ``{slug: {name, ...}}`` shape."""
    agents: dict[str, dict] = {}
    for slug, m in reg.agents.items():
        agents[slug] = {
            "name": m.name,
            "requires_gui": "display" in m.requires,
            "tier": m.tier,
        }
    connectors: dict[str, dict] = {}
    for slug, m in reg.connectors.items():
        connectors[slug] = {
            "name": m.name,
            "requires_gui": "display" in m.requires,
            "tier": m.tier,
        }
    desktops: dict[str, dict] = {}
    for slug, m in reg.desktops.items():
        desktops[slug] = {
            "name": m.name,
            "has_gui": "display" in m.provides,
            "tier": m.tier,
        }
    return agents, connectors, desktops


# One hint for every tag rejection: the fix is always "look at the
# matrix", so the copy-pasteable command lives in exactly one string.
_TAG_HINT = "Run ./sanity-cli list to see the valid tag matrix."


def resolve_tag(tag: str) -> Tag:
    """Parse + registry-validate a dimension tag; the Tag IS the result.

    Validation goes through the manifest-driven registry: unknown slugs
    raise :class:`TagError` with the legacy ``Unknown <kind>`` message,
    and capability conflicts raise :class:`TagError` with a 'requires a
    GUI desktop' phrasing kept for legacy tests / users (the underlying
    solver is generic and supports arbitrary capabilities). TagError
    subclasses ValueError, so existing except-ValueError callers are
    unchanged.
    """
    parts = tag.split("-")
    if len(parts) != 3:
        raise TagError(
            f"Invalid tag format '{tag}'. Expected "
            "{agent}-{desktop}-{connector} (e.g. ag-xfce-kasm)",
            hint=_TAG_HINT,
        )
    agent, desktop, connector = parts
    reg = get_registry()
    if agent not in reg.agents:
        raise TagError(
            f"Unknown agent '{agent}'. Valid: {', '.join(reg.agents.keys())}",
            hint=_TAG_HINT,
        )
    if desktop not in reg.desktops:
        raise TagError(
            f"Unknown desktop '{desktop}'. "
            f"Valid: {', '.join(reg.desktops.keys())}",
            hint=_TAG_HINT,
        )
    if connector not in reg.connectors:
        raise TagError(
            f"Unknown connector '{connector}'. "
            f"Valid: {', '.join(reg.connectors.keys())}",
            hint=_TAG_HINT,
        )

    parsed = Tag(agent=agent, desktop=desktop, connector=connector)
    try:
        _capability_solve(parsed, reg)
    except CapabilityConflictError as exc:
        if "display" in exc.missing:
            connector_m = reg.connectors[connector]
            agent_m = reg.agents[agent]
            if "display" in connector_m.requires:
                raise TagError(
                    f"Connector '{connector}' requires a GUI desktop, "
                    f"but '{desktop}' is headless",
                    hint=_TAG_HINT,
                ) from exc
            if "display" in agent_m.requires:
                raise TagError(
                    f"Agent '{agent}' requires a GUI desktop, "
                    f"but '{desktop}' is headless",
                    hint=_TAG_HINT,
                ) from exc
        raise TagError(str(exc), hint=_TAG_HINT) from exc
    return parsed


def generate_tag_values(tiers: Collection[str] | None = None) -> tuple[Tag, ...]:
    """The matrix as parsed values - the registry builds Tags from
    manifest slugs, so this is where they are already values.

    Exposed alongside the string view because the string view is a
    rendering of this, not the other way round: callers that want
    structure took to re-parsing ``VALID_TAGS`` item by item, which put
    the tag grammar back into three separate call sites.
    """
    return tuple(get_registry().valid_tags(tiers=tiers))


def generate_valid_tags(tiers: Collection[str] | None = None) -> list[str]:
    """Return all tag combinations whose plugins satisfy capabilities.

    ``tiers`` optionally restricts the result to tags whose tier is in
    the given set (see :meth:`PluginRegistry.valid_tags`).
    """
    return [str(t) for t in generate_tag_values(tiers=tiers)]


def tag_tier(tag: Tag) -> str:
    """Tier of a tag value.

    See :meth:`PluginRegistry.tag_tier` - the most restrictive tier
    among the tag's three plugins wins. Takes the value rather than the
    string: splitting a rendered tag back into dimensions here made this
    a second, quieter copy of the tag grammar.
    """
    return get_registry().tag_tier(tag)


def deprecation_warning(tag: Tag) -> str | None:
    """Warning text for a deprecated tag, or ``None`` for other tiers.

    Kept here (next to the tier data) so build/up print the same
    message; the verbs decide how to surface it.
    """
    if tag_tier(tag) != "deprecated":
        return None
    return (
        f"Tag '{tag}' uses a deprecated plugin: it is excluded from CI "
        "and no longer published to GHCR. Local build/up keep working, "
        "but expect no further updates."
    )


# Legacy module-level views. Computed once at import time; they stay
# stable across a process because the manifest set is filesystem-bound.
AGENTS, CONNECTORS, DESKTOPS = _legacy_dim_dicts(get_registry())
#: The matrix as values. VALID_TAGS is its rendering, so the two cannot
#: drift and no caller needs to parse a tag back out of the string list.
VALID_TAG_VALUES = generate_tag_values()
VALID_TAGS = [str(t) for t in VALID_TAG_VALUES]
# The CI build/verify and release publish matrix: official tier only.
# Community/deprecated tags stay in VALID_TAGS (parse + lifecycle) but
# leave every CI enumeration (``list --json`` / ``build all``).
OFFICIAL_TAG_VALUES = generate_tag_values(tiers=("official",))
OFFICIAL_TAGS = [str(t) for t in OFFICIAL_TAG_VALUES]
