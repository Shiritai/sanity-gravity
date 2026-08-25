"""Unit tests for the ``pull`` verb.

``resolve_ghcr_repo`` has a three-level precedence: the
``SANITY_GHCR_REPO`` env var, the ``origin`` git remote (GitHub URLs
only), then the upstream repo as a last resort. Forks must end up
pulling their own GHCR packages without any configuration -- and when
git cannot answer, the fallback to the upstream org must be LOUD, not
silent.

``get_target_version_tag`` resolves exact tag -> short SHA -> latest on
the git *return code* AND on git having actually said something. Both
halves matter: rc==0 with empty stdout is "git answered nothing", which
must fall through rather than yield an empty version tag.

``pull`` itself must expand the default ``all`` to the official tag
matrix (only official tags are published to GHCR), keep going when a
single variant fails (aggregate + exit nonzero at the end), and treat
a scalar variant (as passed by ``up`` auto-pull) as one tag.

Every subprocess outcome here is scripted through the shared
``fake_proc`` fixture, so a command the test did not anticipate is an
error rather than a silent rc=0.
"""
from __future__ import annotations

import argparse

import pytest

from sanity_gravity.verbs import pull as pull_mod

_DESCRIBE = "git describe --tags --exact-match"
_REV_PARSE = "git rev-parse --short HEAD"
_REMOTE = "git remote get-url origin"


class TestResolveGhcrRepo:
    def test_env_var_overrides_git_remote(self, fake_proc, monkeypatch):
        monkeypatch.setenv("SANITY_GHCR_REPO", "SomeOrg/Some-Fork")

        # Nothing is scripted: consulting git at all would raise
        # UnscriptedCommand, which is the assertion.
        assert pull_mod.resolve_ghcr_repo() == "someorg/some-fork"
        assert fake_proc.calls == []

    @pytest.mark.parametrize(
        "url,expected",
        [
            ("git@github.com:Forker/Sanity-Gravity.git", "forker/sanity-gravity"),
            ("https://github.com/forker/sanity-gravity", "forker/sanity-gravity"),
            ("https://github.com/forker/sanity-gravity.git", "forker/sanity-gravity"),
            ("ssh://git@github.com/forker/sanity-gravity.git", "forker/sanity-gravity"),
        ],
    )
    def test_derives_repo_from_origin_remote(
        self, fake_proc, monkeypatch, url, expected,
    ):
        monkeypatch.delenv("SANITY_GHCR_REPO", raising=False)
        fake_proc.script(_REMOTE, stdout=url)
        assert pull_mod.resolve_ghcr_repo() == expected

    def test_git_failure_falls_back_loudly(self, fake_proc, monkeypatch):
        """No origin remote / no git: default to upstream, but WARN --
        the quiet fallback shipped as a real bug: a fork user silently
        pulled the upstream org's images."""
        monkeypatch.delenv("SANITY_GHCR_REPO", raising=False)
        fake_proc.script(_REMOTE, rc=2, stderr="error: No such remote 'origin'")
        warnings: list[str] = []
        monkeypatch.setattr(pull_mod, "print_warning", warnings.append)
        assert pull_mod.resolve_ghcr_repo() == "shiritai/sanity-gravity"
        assert any("shiritai/sanity-gravity" in w for w in warnings)

    def test_non_github_remote_falls_back_to_upstream(
        self, fake_proc, monkeypatch,
    ):
        """Only GitHub remotes can imply a GHCR namespace. A readable
        non-GitHub remote is a deliberate answer, not a failure -- no
        warning."""
        monkeypatch.delenv("SANITY_GHCR_REPO", raising=False)
        fake_proc.script(_REMOTE, stdout="git@gitlab.com:x/y.git")
        warnings: list[str] = []
        monkeypatch.setattr(pull_mod, "print_warning", warnings.append)
        assert pull_mod.resolve_ghcr_repo() == "shiritai/sanity-gravity"
        assert warnings == []


class TestGetTargetVersionTag:
    def test_exact_tag_wins(self, fake_proc):
        fake_proc.script(_DESCRIBE, stdout="v0.3.0-rc.3")
        fake_proc.script(_REV_PARSE, stdout="abc1234")
        assert pull_mod.get_target_version_tag() == "v0.3.0-rc.3"
        # The tag answered, so the SHA stage is never reached.
        fake_proc.assert_never_ran("rev-parse")

    def test_describe_failure_falls_to_sha_on_rc(self, fake_proc):
        """Not on a tag: git describe exits 128 with 'fatal:' on STDERR
        and empty stdout. The decision is the rc; the old
        startswith('fatal:') guard read stdout and was dead code."""
        fake_proc.script(_DESCRIBE, rc=128, stderr="fatal: no tag exactly matches")
        fake_proc.script(_REV_PARSE, stdout="abc1234")
        assert pull_mod.get_target_version_tag() == "sha-abc1234"

    def test_stdout_looking_like_fatal_is_still_a_tag(self, fake_proc):
        """rc==0 means git answered; the answer is not second-guessed by
        sniffing its spelling.

        The string must genuinely start with ``fatal:`` -- that is the
        exact shape the deleted ``startswith("fatal:")`` guard would
        have rejected, so anything else cannot detect its return.
        """
        fake_proc.script(_DESCRIBE, stdout="fatal: not really, this is a tag")
        fake_proc.script(_REV_PARSE, stdout="abc1234")
        assert pull_mod.get_target_version_tag() == (
            "fatal: not really, this is a tag"
        )

    def test_rc_zero_with_empty_stdout_is_not_a_tag(self, fake_proc):
        """rc==0 but git said nothing: "success" alone is not an answer.

        Guards ``if tag.ok and tag.stdout``. Keying on the rc alone would
        return an EMPTY version tag here and pull ``...-<variant>:``.
        """
        fake_proc.script(_DESCRIBE, rc=0, stdout="")
        fake_proc.script(_REV_PARSE, stdout="abc1234")
        assert pull_mod.get_target_version_tag() == "sha-abc1234"

    def test_rc_zero_with_empty_sha_falls_to_latest(self, fake_proc):
        """Same distinction one stage down, guarding
        ``if sha.ok and sha.stdout``: an empty rev-parse must reach the
        'latest' fallback, not yield the ref ``sha-``."""
        fake_proc.script(_DESCRIBE, rc=128, stderr="fatal: no tag")
        fake_proc.script(_REV_PARSE, rc=0, stdout="")
        assert pull_mod.get_target_version_tag() == "latest"

    def test_no_git_at_all_falls_to_latest(self, fake_proc):
        missing = "No such file or directory: 'git'"
        fake_proc.script(_DESCRIBE, rc=127, stderr=missing)
        fake_proc.script(_REV_PARSE, rc=127, stderr=missing)
        assert pull_mod.get_target_version_tag() == "latest"


def _script_docker(fake_proc, failing_images=()):
    """Every docker command succeeds except ``pull`` of a named image.

    The specific per-image rule wins over the general one because the
    longest matching pattern wins.
    """
    fake_proc.script("docker pull")
    fake_proc.script("docker tag")
    for image in failing_images:
        fake_proc.script(f"docker pull {image}", rc=1)


def _pulled_images(fake_proc):
    return [c.argv[2] for c in fake_proc.calls_matching("docker pull")]


def _tag_calls(fake_proc):
    return [c.argv for c in fake_proc.calls_matching("docker tag")]


def test_pull_uses_resolved_repo_in_image_names(fake_proc, monkeypatch):
    """The verb wires the resolved repo into the GHCR image reference."""
    monkeypatch.setenv("SANITY_GHCR_REPO", "myorg/myrepo")
    _script_docker(fake_proc)

    args = argparse.Namespace(variant=["cc-none-ssh"], tag="v9.9.9")
    pull_mod.pull(args)

    assert _pulled_images(fake_proc) == [
        "ghcr.io/myorg/myrepo-cc-none-ssh:v9.9.9",
    ]
    assert ("docker", "tag", "ghcr.io/myorg/myrepo-cc-none-ssh:v9.9.9",
            "sanity-gravity:cc-none-ssh") in _tag_calls(fake_proc)
    fake_proc.assert_no_unscripted()


def test_pull_aggregates_failures_into_a_report(fake_proc, monkeypatch):
    """One failing variant must not abort the rest of the batch, and
    pull() itself never decides the process's fate: it returns a
    PullReport (decision 2 -- the exit moves to the CLI entry)."""
    monkeypatch.setenv("SANITY_GHCR_REPO", "myorg/myrepo")
    _script_docker(
        fake_proc,
        failing_images=("ghcr.io/myorg/myrepo-cx-none-ssh:v9.9.9",),
    )

    args = argparse.Namespace(
        variant=["cc-none-ssh", "cx-none-ssh", "ag-xfce-kasm"], tag="v9.9.9",
    )
    report = pull_mod.pull(args)

    assert report.failed == ("cx-none-ssh",)
    assert report.succeeded == ("cc-none-ssh", "ag-xfce-kasm")
    assert report.ok is False
    # Every variant was attempted, including the ones after the failure.
    assert _pulled_images(fake_proc) == [
        "ghcr.io/myorg/myrepo-cc-none-ssh:v9.9.9",
        "ghcr.io/myorg/myrepo-cx-none-ssh:v9.9.9",
        "ghcr.io/myorg/myrepo-ag-xfce-kasm:v9.9.9",
    ]
    # Only successful pulls are re-tagged locally.
    assert [c[3] for c in _tag_calls(fake_proc)] == [
        "sanity-gravity:cc-none-ssh", "sanity-gravity:ag-xfce-kasm",
    ]


def test_pull_cmd_keeps_the_all_or_nothing_contract(fake_proc, monkeypatch):
    """CLI entry: any failed variant -> SanityError with exit_code 1
    (the boundary exits 1; scripts keep their bit), summary counts both
    sides, and the hint says how to build an unpublished tag."""
    from sanity_gravity.domain.errors import SanityError

    monkeypatch.setenv("SANITY_GHCR_REPO", "myorg/myrepo")
    _script_docker(
        fake_proc,
        failing_images=("ghcr.io/myorg/myrepo-cx-none-ssh:v9.9.9",),
    )

    args = argparse.Namespace(
        variant=["cc-none-ssh", "cx-none-ssh"], tag="v9.9.9",
    )
    with pytest.raises(SanityError) as ei:
        pull_mod.pull_cmd(args)
    assert ei.value.exit_code == 1
    assert "cx-none-ssh" in str(ei.value)
    assert "1 of 2" in str(ei.value)
    assert "sanity-cli build" in (ei.value.hint or "")


def test_pull_cmd_success_prints_the_summary(fake_proc, monkeypatch):
    monkeypatch.setenv("SANITY_GHCR_REPO", "myorg/myrepo")
    _script_docker(fake_proc)
    successes: list[str] = []
    monkeypatch.setattr(pull_mod, "print_success", successes.append)

    args = argparse.Namespace(variant=["cc-none-ssh"], tag="v9.9.9")
    pull_mod.pull_cmd(args)
    assert any("available locally" in m for m in successes)


def test_pull_default_all_expands_to_official_tags(fake_proc, monkeypatch):
    """Bare ``pull`` (parser default ['all']) pulls the publish matrix."""
    from sanity_gravity.core.registry import OFFICIAL_TAGS

    monkeypatch.setenv("SANITY_GHCR_REPO", "myorg/myrepo")
    _script_docker(fake_proc)

    args = argparse.Namespace(variant=["all"], tag="v9.9.9")
    pull_mod.pull(args)

    assert OFFICIAL_TAGS  # guard: the expansion must not be empty
    assert _pulled_images(fake_proc) == [
        f"ghcr.io/myorg/myrepo-{t}:v9.9.9" for t in OFFICIAL_TAGS
    ]


def test_pull_scalar_variant_is_one_tag(fake_proc, monkeypatch):
    """``up`` auto-pull passes its tag as a bare string.

    A scalar must be treated as a single variant, never iterated
    character by character.
    """
    monkeypatch.setenv("SANITY_GHCR_REPO", "myorg/myrepo")
    _script_docker(fake_proc)

    args = argparse.Namespace(variant="cc-none-ssh", tag="v9.9.9")
    pull_mod.pull(args)

    assert _pulled_images(fake_proc) == [
        "ghcr.io/myorg/myrepo-cc-none-ssh:v9.9.9",
    ]
