"""``status`` / ``list`` / ``plugins list`` verbs: read-only inspection."""
from __future__ import annotations

import subprocess

from sanity_gravity.cli.colors import Colors
from sanity_gravity.cli.io import (
    print_error,
    print_header,
    print_info,
    print_plain,
    print_success,
    print_warning,
    run_command,
)
from sanity_gravity.cli.registry import (
    AGENTS,
    BASES,
    CONNECTORS,
    DEFAULT_TAG,
    DESKTOPS,
    OFFICIAL_TAGS,
    VALID_TAGS,
    get_registry,
    tag_tier,
)
from sanity_gravity.domain.tags import DEFAULT_BASE_IMAGE
from sanity_gravity.verbs.lifecycle import (
    get_active_projects,
    get_legacy_projects,
)


def status(args):
    """Show status of sandbox containers."""
    target_project = getattr(args, "name", "sanity-gravity")

    active_projects = get_active_projects()

    if target_project != "sanity-gravity" and target_project not in active_projects:
        print_warning(f"Project '{target_project}' not found in active projects.")

    projects_to_show = []
    if target_project == "sanity-gravity":
        projects_to_show = active_projects
    else:
        projects_to_show = [target_project]

    if not projects_to_show and target_project == "sanity-gravity":
        print_info("No managed Sanity-Gravity instances found.")

    for project in projects_to_show:
        print_header(f"Sandbox Status ({project})")
        try:
            # Identify the project by name only — docker compose looks up
            # active containers via the project label, no compose file needed.
            # (Passing -f to a non-existent file silently returns empty,
            # which is the bug PR #6's modular config layout exposed.)
            output = run_command(
                ("docker", "compose", "-p", project, "ps", "-a"),
                capture=True, check=False,
            )
            if output:
                print_plain(output)
            else:
                print_info("  No containers running.")

            print_plain("")
        except (subprocess.CalledProcessError, SystemExit) as e:
            print_error(f"Failed to get status for {project}: {e}")

    if target_project == "sanity-gravity":
        legacy_projects = get_legacy_projects()
        if legacy_projects:
            print_plain(
                f"\n{Colors.WARNING}⚠ Found {len(legacy_projects)} legacy "
                f"container(s) not managed by Sanity CLI:{Colors.ENDC}"
            )
            for lp in legacy_projects:
                print_plain(f"  - {lp}")
            print_plain(
                f"{Colors.BOLD}Run 'sanity-cli upgrade' to detect and migrate "
                f"them.{Colors.ENDC}"
            )


def _tier_marker(tier: str) -> str:
    """Render a warning-coloured marker for non-official tiers."""
    if tier == "official":
        return ""
    return f" {Colors.WARNING}({tier}){Colors.ENDC}"


def list_variants(args):
    """List available tags with dimension matrix.

    ``--json`` emits the official tier only: it is the enumeration
    source for the CI build/verify and release publish matrices.
    The human-readable listing keeps every valid tag and marks
    non-official tiers instead.
    """
    import json as _json
    if getattr(args, "json_output", False):
        print(_json.dumps(OFFICIAL_TAGS))
        return

    print_header("Dimension Matrix")

    print_plain(f"\n  {Colors.BOLD}Base Images:{Colors.ENDC}")
    for slug, info in BASES.items():
        marker = _tier_marker(info.get("tier", "official"))
        default_tag = (
            f" {Colors.OKGREEN}(default){Colors.ENDC}"
            if slug == DEFAULT_BASE_IMAGE else ""
        )
        print_plain(
            f"    {Colors.OKCYAN}{slug}{Colors.ENDC} = "
            f"{info['name']}{default_tag}{marker}"
        )

    print_plain(f"\n  {Colors.BOLD}Agents:{Colors.ENDC}")
    for slug, info in AGENTS.items():
        gui_tag = (
            f" {Colors.WARNING}(requires GUI){Colors.ENDC}"
            if info["requires_gui"] else ""
        )
        marker = _tier_marker(info.get("tier", "official"))
        print_plain(
            f"    {Colors.OKCYAN}{slug}{Colors.ENDC} = "
            f"{info['name']}{gui_tag}{marker}"
        )

    print_plain(f"\n  {Colors.BOLD}Connectors:{Colors.ENDC}")
    for slug, info in CONNECTORS.items():
        gui_tag = (
            f" {Colors.WARNING}(requires GUI){Colors.ENDC}"
            if info["requires_gui"] else ""
        )
        marker = _tier_marker(info.get("tier", "official"))
        print_plain(
            f"    {Colors.OKCYAN}{slug}{Colors.ENDC} = "
            f"{info['name']}{gui_tag}{marker}"
        )

    print_plain(f"\n  {Colors.BOLD}Desktops:{Colors.ENDC}")
    for slug, info in DESKTOPS.items():
        gui_tag = (
            f" {Colors.OKGREEN}(GUI){Colors.ENDC}" if info["has_gui"]
            else f" {Colors.WARNING}(headless){Colors.ENDC}"
        )
        print_plain(f"    {Colors.OKCYAN}{slug}{Colors.ENDC} = {info['name']}{gui_tag}")

    print_plain(
        f"\n  {Colors.BOLD}Tag format:{Colors.ENDC} "
        "{base-image-}agent-desktop-connector"
    )
    print_plain(
        "    The default base image is elided from the tag "
        f"(e.g. {DEFAULT_TAG}); other bases are prefixed "
        "(e.g. debian-ag-xfce-kasm)."
    )
    print_plain(f"  {Colors.BOLD}Default:{Colors.ENDC} {DEFAULT_TAG}")

    print_plain(f"\n  {Colors.BOLD}All valid tags:{Colors.ENDC}")
    for tag in VALID_TAGS:
        marker = (
            f" {Colors.OKGREEN}(default){Colors.ENDC}"
            if tag == DEFAULT_TAG else ""
        )
        marker += _tier_marker(tag_tier(tag))
        print_plain(f"    {Colors.OKCYAN}{tag}{Colors.ENDC}{marker}")


def plugins_list(args):
    """List manifest-driven plugins discovered under ``plugins/``."""
    reg = get_registry()

    def _render_caps(m):
        provides = ", ".join(m.provides) or "—"
        requires = ", ".join(m.requires) or "—"
        return f"provides=[{provides}] requires=[{requires}]"

    def _render_ports(m):
        if not m.ports:
            return ""
        return " ports=[" + ", ".join(
            f"{p.label}:{p.internal}" for p in m.ports
        ) + "]"

    print_header("Registered Plugins")

    sections = (
        ("Base Images", reg.base_images),
        ("Agents", reg.agents),
        ("Desktops", reg.desktops),
        ("Connectors", reg.connectors),
    )
    for label, bucket in sections:
        print_plain(f"\n  {Colors.BOLD}{label}:{Colors.ENDC}")
        if not bucket:
            print_plain(f"    {Colors.WARNING}(none){Colors.ENDC}")
            continue
        for slug, m in bucket.items():
            line = (
                f"    {Colors.OKCYAN}{slug}{Colors.ENDC} = {m.name}  "
                f"{_render_caps(m)}{_render_ports(m)}{_tier_marker(m.tier)}"
            )
            print_plain(line)

    total = (
        len(reg.base_images)
        + len(reg.agents)
        + len(reg.desktops)
        + len(reg.connectors)
    )
    print_success(f"{total} plugins registered")
