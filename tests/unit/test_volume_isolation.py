"""Per-tag home-volume isolation, at the compose-generation level.

Two tags in one project must declare and mount distinct ``sg_<tag>``
volumes: the home volume is the container's whole persistent state, so
a shared name would silently bleed one agent's dotfiles into another.
The live two-container counterpart runs in
``tests/integration/test_volume_isolation.py``.
"""
import os

import yaml

from sanity_gravity.compose.generators import generate_compose_for_tag

_EXTERNAL_PREFIX = "sg-${COMPOSE_PROJECT_NAME:-sanity-gravity}"


def _generate(tmpdir, tag):
    """Generate into tmpdir (the generator writes under cwd) and parse."""
    old_cwd = os.getcwd()
    os.chdir(str(tmpdir))
    try:
        out, _ = generate_compose_for_tag(tag)
        assert os.path.exists(out)
        with open(out) as f:
            return yaml.safe_load(f)
    finally:
        os.chdir(old_cwd)


class TestVolumeIsolation:
    def test_volume_isolation_different_agents(self, tmpdir):
        """Different agents must mount different sanity_home volumes."""
        yaml_ag = _generate(tmpdir, "ag-xfce-kasm")
        yaml_gc = _generate(tmpdir, "gc-none-ssh")

        volumes_ag = yaml_ag.get("volumes", {})
        volumes_gc = yaml_gc.get("volumes", {})

        # Top-level volume declarations: each file declares exactly its
        # own tag volume.
        assert "sg_ag-xfce-kasm" in volumes_ag
        assert "sg_gc-none-ssh" not in volumes_ag
        assert "sg_gc-none-ssh" in volumes_gc
        assert "sg_ag-xfce-kasm" not in volumes_gc

        # Explicit external names embed the tag, so two projects with
        # the same tag stay distinct too.
        assert volumes_ag["sg_ag-xfce-kasm"]["name"] == (
            f"{_EXTERNAL_PREFIX}-ag-xfce-kasm"
        )
        assert volumes_gc["sg_gc-none-ssh"]["name"] == (
            f"{_EXTERNAL_PREFIX}-gc-none-ssh"
        )

        # Service mounts reference the per-tag volume.
        service_vols_ag = yaml_ag["services"]["ag-xfce-kasm"]["volumes"]
        assert any(v.startswith("sg_ag-xfce-kasm:") for v in service_vols_ag)
        service_vols_gc = yaml_gc["services"]["gc-none-ssh"]["volumes"]
        assert any(v.startswith("sg_gc-none-ssh:") for v in service_vols_gc)

    def test_volume_isolation_same_agent_different_connectors(self, tmpdir):
        """Same agent, different connectors: still distinct volumes -
        the whole tag is the identity, not the agent slug."""
        yaml_kasm = _generate(tmpdir, "ag-xfce-kasm")
        yaml_ssh = _generate(tmpdir, "ag-xfce-ssh")

        assert "sg_ag-xfce-kasm" in yaml_kasm.get("volumes", {})
        assert "sg_ag-xfce-ssh" in yaml_ssh.get("volumes", {})
        assert yaml_kasm["volumes"]["sg_ag-xfce-kasm"]["name"] == (
            f"{_EXTERNAL_PREFIX}-ag-xfce-kasm"
        )
        assert yaml_ssh["volumes"]["sg_ag-xfce-ssh"]["name"] == (
            f"{_EXTERNAL_PREFIX}-ag-xfce-ssh"
        )

        assert "sg_ag-xfce-ssh" not in yaml_kasm.get("volumes", {})
        assert "sg_ag-xfce-kasm" not in yaml_ssh.get("volumes", {})

        assert any(
            v.startswith("sg_ag-xfce-kasm:")
            for v in yaml_kasm["services"]["ag-xfce-kasm"]["volumes"]
        )
        assert any(
            v.startswith("sg_ag-xfce-ssh:")
            for v in yaml_ssh["services"]["ag-xfce-ssh"]["volumes"]
        )
