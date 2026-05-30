"""``pull`` verb: Fetch pre-built Sandbox images from GitHub Container Registry (GHCR).

This implements the 'Local Tag Normalization' pattern. Instead of polluting
docker-compose overlays with remote URLs, we pull the remote image and
immediately re-tag it to the local standard name (sanity-gravity:<variant>).
This ensures 100% compatibility with local dev builds and keeps compose files clean.
"""
from __future__ import annotations

import os

from sanity_gravity.cli.colors import Colors
from sanity_gravity.cli.io import (
    print_error,
    print_header,
    print_info,
    print_success,
    print_warning,
    run_command,
)
from sanity_gravity.cli.registry import get_registry


def get_target_version_tag() -> str:
    """Smartly resolve which version tag to pull from GHCR.

    1. Exact git tag (e.g., v0.3.0-rc.3)
    2. Short SHA if on a commit (e.g., sha-abc1234)
    3. Fallback to 'latest'
    """
    # 1. Try to get exact tag
    tag_out = run_command(("git", "describe", "--tags", "--exact-match"), capture=True, check=False)
    if tag_out and not tag_out.startswith("fatal:"):
        return tag_out.strip()

    # 2. Try to get short SHA
    sha_out = run_command(("git", "rev-parse", "--short", "HEAD"), capture=True, check=False)
    if sha_out and not sha_out.startswith("fatal:"):
        return f"sha-{sha_out.strip()}"

    # 3. Fallback
    return "latest"


def pull(args):
    """Entry point for the ``pull`` command."""
    variants = args.variant
    if "all" in variants:
        variants = list(get_registry().expand_wildcards(["*"]))

    version_tag = args.tag if hasattr(args, "tag") and args.tag else get_target_version_tag()
    repo_lc = "shiritai/sanity-gravity"  # Hardcoded repo owner/name for GHCR

    print_header(f"Pulling {len(variants)} variant(s) (Version: {version_tag})")

    failed = []
    for variant in variants:
        ghcr_image = f"ghcr.io/{repo_lc}-{variant}:{version_tag}"
        local_image = f"sanity-gravity:{variant}"

        print_info(f"[{variant}] Pulling {ghcr_image} ...")
        # Let docker pull output directly to the terminal for progress bars
        out = run_command(("docker", "pull", ghcr_image), check=False)
        
        if out is None:  # In non-dry-run mode, if check=False and it fails, run_command might exit? 
            # Wait, `run_command` in io.py calls sys.exit if check=True. If check=False, it returns stdout or empty string.
            pass

        # Let's check if the image actually exists locally now
        check_out = run_command(("docker", "image", "inspect", ghcr_image), capture=True, check=False)
        if not check_out or check_out.strip() == "[]" or "Error: No such image" in check_out:
            print_error(f"Failed to pull {ghcr_image}")
            failed.append(variant)
            continue

        print_info(f"[{variant}] Re-tagging to {local_image} ...")
        run_command(("docker", "tag", ghcr_image, local_image))
        print_success(f"[{variant}] Successfully normalized local tag.")

    if failed:
        print_error(f"Failed to pull the following variants: {', '.join(failed)}")
        import sys
        sys.exit(1)
    
    print_success("All requested images are now available locally!")
