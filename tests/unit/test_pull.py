"""Unit tests for the ``pull`` verb's GHCR repo resolution.

``resolve_ghcr_repo`` has a three-level precedence: the
``SANITY_GHCR_REPO`` env var, the ``origin`` git remote (GitHub URLs
only), then the upstream repo as a last resort. Forks must end up
pulling their own GHCR packages without any configuration.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from sanity_gravity.verbs import pull as pull_mod  # noqa: E402


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


def test_pull_uses_resolved_repo_in_image_names(monkeypatch):
    """The verb wires the resolved repo into the GHCR image reference."""
    import argparse

    monkeypatch.setenv("SANITY_GHCR_REPO", "myorg/myrepo")
    commands: list[tuple] = []

    def _run(cmd, **kw):
        commands.append(tuple(cmd))
        if cmd[:3] == ("docker", "image", "inspect"):
            return '[{"Id": "sha256:x"}]'  # image present after pull
        return ""

    monkeypatch.setattr(pull_mod, "run_command", _run)
    args = argparse.Namespace(variant=["cc-none-ssh"], tag="v9.9.9")
    pull_mod.pull(args)

    pulls = [c for c in commands if c[:2] == ("docker", "pull")]
    assert pulls == [
        ("docker", "pull", "ghcr.io/myorg/myrepo-cc-none-ssh:v9.9.9"),
    ]
    assert ("docker", "tag", "ghcr.io/myorg/myrepo-cc-none-ssh:v9.9.9",
            "sanity-gravity:cc-none-ssh") in commands
