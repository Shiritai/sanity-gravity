"""Lazy plugin registry + legacy dimension projections + tag parser.

The legacy ``AGENTS`` / ``CONNECTORS`` / ``DESKTOPS`` dicts are derived
from the manifest-driven registry and exposed here for back-compat with
tests and verbs that grew up reading them. ``parse_tag`` performs
constraint validation via the capability solver, mapping the technical
"missing capability" error back to the user-friendly
"requires a GUI desktop" phrasing.
"""
from __future__ import annotations

import os
from collections.abc import Collection

from sanity_gravity.domain.capability import CapabilityConflictError
from sanity_gravity.domain.capability import solve as _capability_solve
from sanity_gravity.domain.tags import DEFAULT_BASE_IMAGE, Tag
from sanity_gravity.plugins.registry import default_registry as _default_registry


PLUGINS_DIR = "plugins"
DEFAULT_TAG = "ag-xfce-kasm"


def _repo_root() -> str:
    """Return the repository root (3 dirs up from this file).

    This file lives at ``<repo>/sanity_gravity/cli/registry.py``.
    """
    return os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )


def get_registry():
    """Lazy accessor: load manifests from ``plugins/`` once per process."""
    return _default_registry(os.path.join(_repo_root(), PLUGINS_DIR))


def _legacy_dim_dicts(reg):
    """Project the registry into the legacy ``{slug: {name, ...}}`` shape."""
    bases: dict[str, dict] = {}
    for slug, m in reg.base_images.items():
        bases[slug] = {
            "name": m.name,
            "tier": m.tier,
        }
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
    return bases, agents, connectors, desktops


def parse_tag(tag):
    """Parse a dimension tag into ``(base_image, agent, desktop, connector)``.

    Accepts both ``agent-desktop-connector`` (default base) and
    ``base_image-agent-desktop-connector`` forms. The default base is
    always valid even before a matching ``base-image`` plugin exists;
    non-default base slugs must be registered.

    Validation goes through the manifest-driven registry: unknown slugs
    raise ``ValueError`` with the legacy ``Unknown <kind>`` message, and
    capability conflicts raise ``ValueError`` with a 'requires a GUI
    desktop' phrasing kept for legacy tests / users (the underlying
    solver is generic and supports arbitrary capabilities).
    """
    parts = tag.split("-")
    if len(parts) == 4:
        base_image, agent, desktop, connector = parts
    elif len(parts) == 3:
        base_image, agent, desktop, connector = DEFAULT_BASE_IMAGE, *parts
    else:
        raise ValueError(
            f"Invalid tag format '{tag}'. Expected "
            "{base_image-}agent-desktop-connector "
            "(e.g. ag-xfce-kasm or debian-ag-xfce-kasm)"
        )
    reg = get_registry()
    if base_image != DEFAULT_BASE_IMAGE and base_image not in reg.base_images:
        raise ValueError(
            f"Unknown base image '{base_image}'. "
            f"Valid: {', '.join(reg.base_images.keys())}"
        )
    if agent not in reg.agents:
        raise ValueError(
            f"Unknown agent '{agent}'. Valid: {', '.join(reg.agents.keys())}"
        )
    if desktop not in reg.desktops:
        raise ValueError(
            f"Unknown desktop '{desktop}'. Valid: {', '.join(reg.desktops.keys())}"
        )
    if connector not in reg.connectors:
        raise ValueError(
            f"Unknown connector '{connector}'. "
            f"Valid: {', '.join(reg.connectors.keys())}"
        )

    parsed = Tag(agent=agent, desktop=desktop, connector=connector, base_image=base_image)
    try:
        _capability_solve(parsed, reg)
    except CapabilityConflictError as exc:
        if "display" in exc.missing:
            connector_m = reg.connectors[connector]
            agent_m = reg.agents[agent]
            if "display" in connector_m.requires:
                raise ValueError(
                    f"Connector '{connector}' requires a GUI desktop, "
                    f"but '{desktop}' is headless"
                ) from exc
            if "display" in agent_m.requires:
                raise ValueError(
                    f"Agent '{agent}' requires a GUI desktop, "
                    f"but '{desktop}' is headless"
                ) from exc
        raise ValueError(str(exc)) from exc
    return base_image, agent, desktop, connector


def generate_valid_tags(tiers: Collection[str] | None = None) -> list[str]:
    """Return all tag combinations whose plugins satisfy capabilities.

    ``tiers`` optionally restricts the result to tags whose tier is in
    the given set (see :meth:`PluginRegistry.valid_tags`).
    """
    return [str(t) for t in get_registry().valid_tags(tiers=tiers)]


def tag_tier(tag: str) -> str:
    """Tier of a well-formed ``{base_image-}agent-desktop-connector`` string.

    See :meth:`PluginRegistry.tag_tier` - the most restrictive tier
    among the tag's plugins wins.
    """
    base_image, agent, desktop, connector = parse_tag(tag)
    return get_registry().tag_tier(
        Tag(agent=agent, desktop=desktop, connector=connector, base_image=base_image)
    )


def deprecation_warning(tag: str) -> str | None:
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
BASES, AGENTS, CONNECTORS, DESKTOPS = _legacy_dim_dicts(get_registry())
VALID_TAGS = generate_valid_tags()
# The CI build/verify and release publish matrix: official tier only.
# Community/deprecated tags stay in VALID_TAGS (parse + lifecycle) but
# leave every CI enumeration (``list --json`` / ``build all``).
OFFICIAL_TAGS = generate_valid_tags(tiers=("official",))
