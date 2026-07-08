"""``pull`` verb: Fetch pre-built Sandbox images from GitHub Container Registry (GHCR).

This implements the 'Local Tag Normalization' pattern. Instead of polluting
docker-compose overlays with remote URLs, we pull the remote image and
immediately re-tag it to the local standard name (sanity-gravity:<variant>).
This ensures 100% compatibility with local dev builds and keeps compose files clean.
"""
from __future__ import annotations

import os
import re
import sys

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


# Upstream repo, used only when neither the env var nor the git remote
# yields a GHCR namespace (e.g. a tarball download without git).
_DEFAULT_GHCR_REPO = "shiritai/sanity-gravity"

# The common GitHub remote URL shapes: scp-like git@host:owner/name,
# https://host/owner/name and ssh://git@host/owner/name, with an
# optional trailing .git. Only GitHub remotes can imply a GHCR namespace.
_GITHUB_REMOTE_RE = re.compile(
    r"^(?:https://|ssh://git@|git@)github\.com[:/]"
    r"(?P<owner>[^/\s]+)/(?P<name>[^/\s]+?)(?:\.git)?/?$"
)


def resolve_ghcr_repo() -> str:
    """Resolve the ``owner/name`` GHCR prefix to pull images from.

    Precedence: ``SANITY_GHCR_REPO`` env var -> the ``origin`` git
    remote -> the upstream repo. Forks therefore pull their own GHCR
    packages without any configuration. GHCR image names are
    lowercase-only, so every source is normalized.
    """
    override = os.environ.get("SANITY_GHCR_REPO", "").strip()
    if override:
        return override.lower()

    url = run_command(
        ("git", "remote", "get-url", "origin"), capture=True, check=False,
    )
    if url:
        m = _GITHUB_REMOTE_RE.match(url.strip())
        if m:
            return f"{m.group('owner')}/{m.group('name')}".lower()

    return _DEFAULT_GHCR_REPO


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
    repo_lc = resolve_ghcr_repo()

    print_header(f"Pulling {len(variants)} variant(s) (Version: {version_tag})")

    failed = []
    for variant in variants:
        ghcr_image = f"ghcr.io/{repo_lc}-{variant}:{version_tag}"
        local_image = f"sanity-gravity:{variant}"

        print_info(f"[{variant}] Pulling {ghcr_image} ...")
        # Let docker pull output directly to the terminal for progress bars
        run_command(("docker", "pull", ghcr_image), check=False)

        # Check whether the image actually exists locally now
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
        sys.exit(1)

    print_success("All requested images are now available locally!")
