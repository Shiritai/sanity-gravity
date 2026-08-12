"""Unit tests for the ``pull`` verb.

``resolve_ghcr_repo`` has a three-level precedence: the
``SANITY_GHCR_REPO`` env var, the ``origin`` git remote (GitHub URLs
only), then the upstream repo as a last resort. Forks must end up
pulling their own GHCR packages without any configuration.

``pull`` itself must expand the default ``all`` to the official tag
matrix (only official tags are published to GHCR), keep going when a
single variant fails (aggregate + exit nonzero at the end), and treat
a scalar variant (as passed by ``up`` auto-pull) as one tag.
"""
from __future__ import annotations

import pytest


from sanity_gravity.verbs import pull as pull_mod


def test_env_var_overrides_git_remote(monkeypatch):
    monkeypatch.setenv("SANITY_GHCR_REPO", "SomeOrg/Some-Fork")

    def _no_git(*a, **kw):
        pytest.fail("env override must not consult git")

    monkeypatch.setattr(pull_mod, "run_command", _no_git)
    # GHCR image names are lowercase-only; the override is normalized.
    assert pull_mod.resolve_ghcr_repo() == "someorg/some-fork"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("git@github.com:Forker/Sanity-Gravity.git", "forker/sanity-gravity"),
        ("https://github.com/forker/sanity-gravity", "forker/sanity-gravity"),
        ("https://github.com/forker/sanity-gravity.git", "forker/sanity-gravity"),
        ("ssh://git@github.com/forker/sanity-gravity.git", "forker/sanity-gravity"),
    ],
)
def test_derives_repo_from_origin_remote(monkeypatch, url, expected):
    monkeypatch.delenv("SANITY_GHCR_REPO", raising=False)
    monkeypatch.setattr(pull_mod, "run_command", lambda *a, **kw: url)
    assert pull_mod.resolve_ghcr_repo() == expected


def test_falls_back_to_upstream_without_origin_remote(monkeypatch):
    """No origin remote (or git failure): run_command yields ''."""
    monkeypatch.delenv("SANITY_GHCR_REPO", raising=False)
    monkeypatch.setattr(pull_mod, "run_command", lambda *a, **kw: "")
    assert pull_mod.resolve_ghcr_repo() == "shiritai/sanity-gravity"


def test_non_github_remote_falls_back_to_upstream(monkeypatch):
    """Only GitHub remotes can imply a GHCR namespace."""
    monkeypatch.delenv("SANITY_GHCR_REPO", raising=False)
    monkeypatch.setattr(
        pull_mod, "run_command", lambda *a, **kw: "git@gitlab.com:x/y.git"
    )
    assert pull_mod.resolve_ghcr_repo() == "shiritai/sanity-gravity"


def _install_fake_run(monkeypatch, commands, failing_images=()):
    """Route ``run_command`` to a recorder that mimics its contract.

    Non-capture calls return an exit code (``docker pull`` of an image
    in ``failing_images`` fails with 1), capture calls return stdout.
    """
    def _run(cmd, capture=False, check=True, **kw):
        commands.append(tuple(cmd))
        if capture:
            return ""
        if tuple(cmd[:2]) == ("docker", "pull") and cmd[2] in failing_images:
            return 1
        return 0

    monkeypatch.setattr(pull_mod, "run_command", _run)


def _pulled_images(commands):
    return [c[2] for c in commands if c[:2] == ("docker", "pull")]


def test_pull_uses_resolved_repo_in_image_names(monkeypatch):
    """The verb wires the resolved repo into the GHCR image reference."""
    import argparse

    monkeypatch.setenv("SANITY_GHCR_REPO", "myorg/myrepo")
    commands: list[tuple] = []
    _install_fake_run(monkeypatch, commands)

    args = argparse.Namespace(variant=["cc-none-ssh"], tag="v9.9.9")
    pull_mod.pull(args)

    assert _pulled_images(commands) == [
        "ghcr.io/myorg/myrepo-cc-none-ssh:v9.9.9",
    ]
    assert ("docker", "tag", "ghcr.io/myorg/myrepo-cc-none-ssh:v9.9.9",
            "sanity-gravity:cc-none-ssh") in commands


def test_pull_aggregates_failures_and_exits_nonzero(monkeypatch):
    """One failing variant must not abort the rest of the batch."""
    import argparse

    monkeypatch.setenv("SANITY_GHCR_REPO", "myorg/myrepo")
    commands: list[tuple] = []
    _install_fake_run(
        monkeypatch, commands,
        failing_images=("ghcr.io/myorg/myrepo-cx-none-ssh:v9.9.9",),
    )
    errors: list[str] = []
    monkeypatch.setattr(pull_mod, "print_error", errors.append)

    args = argparse.Namespace(
        variant=["cc-none-ssh", "cx-none-ssh", "ag-xfce-kasm"], tag="v9.9.9",
    )
    with pytest.raises(SystemExit) as ei:
        pull_mod.pull(args)

    assert ei.value.code == 1
    # Every variant was attempted, including the ones after the failure.
    assert _pulled_images(commands) == [
        "ghcr.io/myorg/myrepo-cc-none-ssh:v9.9.9",
        "ghcr.io/myorg/myrepo-cx-none-ssh:v9.9.9",
        "ghcr.io/myorg/myrepo-ag-xfce-kasm:v9.9.9",
    ]
    # Only successful pulls are re-tagged locally.
    tagged = [c[3] for c in commands if c[:2] == ("docker", "tag")]
    assert tagged == ["sanity-gravity:cc-none-ssh", "sanity-gravity:ag-xfce-kasm"]
    # The summary names the failed variant.
    assert any("cx-none-ssh" in e for e in errors)


def test_pull_default_all_expands_to_official_tags(monkeypatch):
    """Bare ``pull`` (parser default ['all']) pulls the publish matrix."""
    import argparse

    from sanity_gravity.cli.registry import OFFICIAL_TAGS

    monkeypatch.setenv("SANITY_GHCR_REPO", "myorg/myrepo")
    commands: list[tuple] = []
    _install_fake_run(monkeypatch, commands)

    args = argparse.Namespace(variant=["all"], tag="v9.9.9")
    pull_mod.pull(args)

    assert OFFICIAL_TAGS  # guard: the expansion must not be empty
    assert _pulled_images(commands) == [
        f"ghcr.io/myorg/myrepo-{t}:v9.9.9" for t in OFFICIAL_TAGS
    ]


def test_pull_scalar_variant_is_one_tag(monkeypatch):
    """``up`` auto-pull passes its tag as a bare string.

    A scalar must be treated as a single variant, never iterated
    character by character.
    """
    import argparse

    monkeypatch.setenv("SANITY_GHCR_REPO", "myorg/myrepo")
    commands: list[tuple] = []
    _install_fake_run(monkeypatch, commands)

    args = argparse.Namespace(variant="cc-none-ssh", tag="v9.9.9")
    pull_mod.pull(args)

    assert _pulled_images(commands) == [
        "ghcr.io/myorg/myrepo-cc-none-ssh:v9.9.9",
    ]
