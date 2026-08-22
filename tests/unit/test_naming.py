"""Naming: the single source of every name derived from a sandbox identity.

Each method owns exactly one f-string; these tests pin the exact
renderings so any grammar change is a deliberate, visible act. The
cross-family distinctness test prevents two names from ever being
"simplified" into one.
"""
from __future__ import annotations

import pytest

from sanity_gravity.domain.naming import Naming, NamingError
from sanity_gravity.domain.tags import Tag

TAG = Tag.parse("ag-xfce-kasm")


def _naming(project="proj"):
    return Naming(TAG, project)


def test_tag_only_names():
    n = Naming(TAG)
    assert n.image() == "sanity-gravity:ag-xfce-kasm"
    assert n.service() == "ag-xfce-kasm"
    assert n.env_var() == "SANITY_IMAGE_AG_XFCE_KASM"
    assert n.image_expr() == (
        "${SANITY_IMAGE_AG_XFCE_KASM:-sanity-gravity:ag-xfce-kasm}"
    )
    assert n.volume() == "sg_ag-xfce-kasm"
    assert n.compose_file() == "config/docker-compose.ag-xfce-kasm.yml"
    assert n.ghcr("owner/sanity-gravity", "v0.3.0") == (
        "ghcr.io/owner/sanity-gravity-ag-xfce-kasm:v0.3.0"
    )


def test_project_scoped_names():
    n = _naming()
    assert n.container() == "proj-ag-xfce-kasm-1"
    assert n.volume_external() == "sg-proj-ag-xfce-kasm"
    assert n.volume_external("${COMPOSE_PROJECT_NAME:-sanity-gravity}") == (
        "sg-${COMPOSE_PROJECT_NAME:-sanity-gravity}-ag-xfce-kasm"
    )
    assert n.backup_image("20260817") == "sanity-migrate/proj-ag-xfce-kasm:20260817"


def test_project_scoped_names_require_a_project():
    n = Naming(TAG)
    for method in (n.container, n.volume_external, lambda: n.backup_image("t")):
        with pytest.raises(NamingError):
            method()


def test_env_var_and_image_expr_agree():
    """--image works only because the setter side and the compose reader
    side use the same variable name; with one owner they cannot drift."""
    n = Naming(TAG)
    assert n.env_var() in n.image_expr()
    assert n.image() in n.image_expr()


def test_families_are_pairwise_distinct():
    n = _naming()
    rendered = [
        n.image(), n.service(), n.env_var(), n.volume(),
        n.compose_file(), n.container(), n.volume_external(),
    ]
    assert len(set(rendered)) == len(rendered)
