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
from sanity_gravity.cli.registry import OFFICIAL_TAGS
from sanity_gravity.domain.naming import Naming
from sanity_gravity.domain.tags import Tag, TagError


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
    # The CLI parser hands over a list; ``up`` (auto-pull / --pull)
    # passes its single tag as a bare string. Normalize here so a
    # scalar is one variant, never iterated character by character.
    if isinstance(variants, str):
        variants = [variants]
    if "all" in variants:
        # Only official-tier tags are published to GHCR, so the
        # wildcard expands to exactly the CI/publish matrix.
        variants = list(OFFICIAL_TAGS)

    version_tag = args.tag if hasattr(args, "tag") and args.tag else get_target_version_tag()
    repo_lc = resolve_ghcr_repo()

    print_header(f"Pulling {len(variants)} variant(s) (Version: {version_tag})")

    failed = []
    for variant in variants:
        # Identity boundary: the CLI hands over strings; parse once and
        # derive both refs from Naming. A malformed variant joins the
        # failed list (aggregate + exit nonzero below) instead of being
        # sent to docker as a ref that cannot exist - the all-or-nothing
        # exit contract is unchanged.
        try:
            naming = Naming(Tag.parse(variant))
        except TagError as e:
            print_error(f"[{variant}] {e}")
            failed.append(variant)
            continue
        ghcr_image = naming.ghcr(repo_lc, version_tag)
        local_image = naming.image()

        print_info(f"[{variant}] Pulling {ghcr_image} ...")
        # Let docker pull output directly to the terminal for progress
        # bars; check=False so one missing variant does not abort the
        # rest, the failure is aggregated below instead.
        rc = run_command(("docker", "pull", ghcr_image), check=False)
        if rc != 0:
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
