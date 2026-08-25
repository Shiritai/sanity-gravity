"""Naming: the single source of every name derived from a sandbox identity.

Each method owns exactly one f-string; the table below pins the exact
renderings so any grammar change is a deliberate, visible act. The
cross-family distinctness test prevents two names from ever being
"simplified" into one.
"""
from __future__ import annotations

import pytest

from sanity_gravity.domain.naming import Naming, NamingError
from sanity_gravity.domain.tags import Tag

TAG = Tag.parse("ag-xfce-kasm")

#: (method, args, exact rendering) - one row per name family surface.
RENDERS = [
    ("image", (), "sanity-gravity:ag-xfce-kasm"),
    ("service", (), "ag-xfce-kasm"),
    ("env_var", (), "SANITY_IMAGE_AG_XFCE_KASM"),
    ("image_expr", (), "${SANITY_IMAGE_AG_XFCE_KASM:-sanity-gravity:ag-xfce-kasm}"),
    ("volume", (), "sg_ag-xfce-kasm"),
    ("compose_file", (), "config/docker-compose.ag-xfce-kasm.yml"),
    ("ghcr", ("owner/sanity-gravity", "v0.3.0"),
     "ghcr.io/owner/sanity-gravity-ag-xfce-kasm:v0.3.0"),
    ("container", (), "proj-ag-xfce-kasm-1"),
    ("volume_external", (), "sg-proj-ag-xfce-kasm"),
    ("volume_external", ("${COMPOSE_PROJECT_NAME:-sanity-gravity}",),
     "sg-${COMPOSE_PROJECT_NAME:-sanity-gravity}-ag-xfce-kasm"),
    ("backup_image", ("20260817",), "sanity-migrate/proj-ag-xfce-kasm:20260817"),
]


@pytest.mark.parametrize(
    "method,args,expected", RENDERS,
    ids=[f"{m}{'#' + str(a[0])[:12] if a else ''}" for m, a, _ in RENDERS],
)
def test_every_name_renders_exactly(method, args, expected):
    assert getattr(Naming(TAG, "proj"), method)(*args) == expected


@pytest.mark.parametrize("method,args", [
    ("container", ()), ("volume_external", ()), ("backup_image", ("t",)),
])
def test_project_scoped_names_require_a_project(method, args):
    with pytest.raises(NamingError):
        getattr(Naming(TAG), method)(*args)


def test_families_are_pairwise_distinct():
    """No two name families may ever be "simplified" into one.

    Not implied by the RENDERS table, despite the table pinning every
    one of these renderings exactly: the table checks each row against
    its own literal, so a future row whose literal duplicates another
    row's would keep the table green while collapsing two families into
    the same name. This test is the only thing that reads the
    renderings against *each other*.
    """
    n = Naming(TAG, "proj")
    rendered = [
        n.image(), n.service(), n.env_var(), n.volume(),
        n.compose_file(), n.container(), n.volume_external(),
    ]
    assert len(set(rendered)) == len(rendered)
