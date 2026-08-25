"""``pull`` verb: Fetch pre-built Sandbox images from GitHub Container Registry (GHCR).

This implements the 'Local Tag Normalization' pattern. Instead of polluting
docker-compose overlays with remote URLs, we pull the remote image and
immediately re-tag it to the local standard name (sanity-gravity:<variant>).
This ensures 100% compatibility with local dev builds and keeps compose files clean.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from sanity_gravity.cli.io import (
    print_error,
    print_header,
    print_info,
    print_success,
    print_warning,
)
from sanity_gravity.core.proc import try_run
from sanity_gravity.core.registry import OFFICIAL_TAG_VALUES
from sanity_gravity.domain.errors import SanityError
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

    res = try_run(("git", "remote", "get-url", "origin"))
    if not res.ok:
        # git missing, not a repo, or no origin remote: the documented
        # tarball-download fallback -- but LOUD, because the quiet
        # fallback shipped a real bug: a fork user silently pulled the
        # upstream org's images. A readable non-GitHub remote below
        # stays quiet: that answer is deliberate, not a failure.
        detail = res.stderr.splitlines()[0] if res.stderr else f"exit {res.returncode}"
        print_warning(
            f"Could not read the origin git remote ({detail}); "
            f"defaulting to GHCR repo '{_DEFAULT_GHCR_REPO}'. "
            "Set SANITY_GHCR_REPO=owner/name to override."
        )
        return _DEFAULT_GHCR_REPO
    if res.stdout:
        m = _GITHUB_REMOTE_RE.match(res.stdout.strip())
        if m:
            return f"{m.group('owner')}/{m.group('name')}".lower()

    return _DEFAULT_GHCR_REPO


def get_target_version_tag() -> str:
    """Smartly resolve which version tag to pull from GHCR.

    1. Exact git tag (e.g., v0.3.0-rc.3)
    2. Short SHA if on a commit (e.g., sha-abc1234)
    3. Fallback to 'latest'

    Each stage decides on git's return code. (The historical
    ``startswith("fatal:")`` stdout sniffing was dead code: git writes
    ``fatal:`` to stderr, which the old capture dropped.)
    """
    # 1. Try to get exact tag
    tag = try_run(("git", "describe", "--tags", "--exact-match"))
    if tag.ok and tag.stdout:
        return tag.stdout

    # 2. Try to get short SHA
    sha = try_run(("git", "rev-parse", "--short", "HEAD"))
    if sha.ok and sha.stdout:
        return f"sha-{sha.stdout}"

    # 3. Fallback
    return "latest"


@dataclass(frozen=True)
class PullReport:
    """Aggregate outcome of one pull run.

    ``pull()`` reports; its callers decide. The CLI entry keeps the
    all-or-nothing contract (any failure -> exit 1); ``up`` emits its
    own message before failing (decision 2).
    """

    succeeded: tuple[str, ...]
    failed: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.failed



def _as_tag(variant: Tag | str) -> Tag:
    """The argv boundary for ``pull``: a user-typed variant becomes a
    value here, once.

    ``--variant all`` expands to the registry's already-parsed matrix, so
    those arrive as values and are passed through untouched rather than
    rendered and re-parsed.
    """
    return variant if isinstance(variant, Tag) else Tag.parse(variant)

def pull(args) -> PullReport:
    """Pull + locally re-tag each requested variant; aggregate outcomes."""
    variants = args.variant
    # The CLI parser hands over a list; ``up`` (auto-pull / --pull)
    # passes its single tag as a bare string. Normalize here so a
    # scalar is one variant, never iterated character by character.
    if isinstance(variants, str):
        variants = [variants]
    if "all" in variants:
        # Only official-tier tags are published to GHCR, so the wildcard
        # expands to exactly the CI/publish matrix - as values, since the
        # registry already parsed them.
        variants = list(OFFICIAL_TAG_VALUES)

    version_tag = args.tag if hasattr(args, "tag") and args.tag else get_target_version_tag()
    repo_lc = resolve_ghcr_repo()

    print_header(f"Pulling {len(variants)} variant(s) (Version: {version_tag})")

    succeeded = []
    failed = []
    for variant in variants:
        # Identity boundary: the CLI hands over strings; parse once and
        # derive both refs from Naming. A malformed variant joins the
        # failed list (aggregate + exit nonzero below) instead of being
        # sent to docker as a ref that cannot exist - the all-or-nothing
        # exit contract is unchanged.
        try:
            naming = Naming(_as_tag(variant))
        except TagError as e:
            print_error(f"[{variant}] {e}")
            failed.append(variant)
            continue
        ghcr_image = naming.ghcr(repo_lc, version_tag)
        local_image = naming.image()

        print_info(f"[{variant}] Pulling {ghcr_image} ...")
        # Stream docker pull to the terminal for progress bars; the rc
        # is matched so one missing variant does not abort the rest,
        # the failure is aggregated below instead.
        res = try_run(("docker", "pull", ghcr_image), capture=False, echo=True)
        if not res.ok:
            print_error(f"Failed to pull {ghcr_image}")
            failed.append(variant)
            continue

        print_info(f"[{variant}] Re-tagging to {local_image} ...")
        try_run(
            ("docker", "tag", ghcr_image, local_image),
            capture=False, echo=True,
        ).raise_for_status()
        print_success(f"[{variant}] Successfully normalized local tag.")
        succeeded.append(variant)

    return PullReport(succeeded=tuple(succeeded), failed=tuple(failed))


def pull_cmd(args) -> None:
    """CLI entry for ``pull``: render the summary, decide the exit.

    The all-or-nothing contract lives HERE, once: scripts rely on the
    exit bit meaning "the requested matrix landed completely".
    """
    report = pull(args)
    if not report.ok:
        total = len(report.succeeded) + len(report.failed)
        raise SanityError(
            f"Failed to pull {len(report.failed)} of {total} variant(s): "
            f"{', '.join(report.failed)}",
            hint=(
                "A tag that is not published to GHCR can be built "
                "locally: ./sanity-cli build <tag>"
            ),
        )
    print_success("All requested images are now available locally!")
