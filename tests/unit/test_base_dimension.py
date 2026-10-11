"""Facts about the base dimension that are stated in two places.

A plugin that only runs on some distros states them twice: as a
``requires`` alternative and in its own Dockerfile. Each test here
reads both places and holds them equal.
"""
from __future__ import annotations

import re

from sanity_gravity.plugins.registry import PluginRegistry
from tests.support import REPO_ROOT

#: A case label of the sha256 table in plugins/connectors/kasm/Dockerfile,
#: e.g. "ubuntu:noble/amd64)". The distro part is the
#: ${ID}:${VERSION_CODENAME} key a base-image plugin provides.
_KASM_CASE_LABEL = re.compile(r"^\s*([a-z][a-z0-9]*:[a-z]+)/(?:amd64|arm64)\)")


def test_kasm_requires_exactly_the_distros_it_pins_a_deb_for():
    """The manifest decides which tags exist, the Dockerfile which debs
    install; if the lists drift, a tag either vanishes for no reason or
    exists and fails its build. Stopping a build on an unlisted distro
    is the Dockerfile's ``*)`` branch; this test keeps the two lists
    equal and does not check the sums."""
    kasm_dir = REPO_ROOT / "plugins" / "connectors" / "kasm"
    labels = {
        m.group(1)
        for line in (kasm_dir / "Dockerfile").read_text().splitlines()
        if (m := _KASM_CASE_LABEL.match(line))
    }
    assert labels, "no case label matched; the pattern no longer fits the Dockerfile"
    kasm = PluginRegistry.from_dir(REPO_ROOT / "plugins").get("connector", "kasm")
    distros = {a for r in kasm.requires for a in r.split("|") if ":" in a}
    assert distros == labels
