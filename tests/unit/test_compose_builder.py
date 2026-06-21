"""Tests for the typed ComposeBuilder introduced in PR #3.

Coverage goals:
- ComposeService.to_dict round-trips through yaml.safe_load.
- ComposeBuilder.render emits valid, block-style YAML.
- patch / merge_* operations are additive and idempotent.
- ${VAR:-default} placeholders survive yaml.safe_dump verbatim.
- Numeric-looking values (cpus='1.5') get quoted; '512m' is left bare.
- Snapshot test on generate_compose_for_tag('ag-xfce-kasm') produces the
  expected service shape (no byte equality required — structural only).
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path

import pytest
import yaml

# Make the package importable the same way sanity-cli does.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from sanity_gravity.compose.builder import ComposeBuilder, ComposeService  # noqa: E402


# -- ComposeService -------------------------------------------------------


def test_compose_service_round_trip():
    """to_dict + yaml.safe_dump + yaml.safe_load must yield the same shape."""
    svc = ComposeService(
        name="svc",
        image="alpine:latest",
        environment={"FOO": "bar"},
        ports=["8080:80"],
        labels={"key": "value"},
    )
    rendered = yaml.safe_dump({"services": {svc.name: svc.to_dict()}})
    parsed = yaml.safe_load(rendered)
    assert parsed["services"]["svc"]["image"] == "alpine:latest"
    assert parsed["services"]["svc"]["environment"] == ["FOO=bar"]
    assert parsed["services"]["svc"]["ports"] == ["8080:80"]
    assert parsed["services"]["svc"]["labels"] == {"key": "value"}


def test_compose_service_omits_empty_fields():
    """Optional/empty fields must not appear in the rendered dict."""
    svc = ComposeService(name="bare", image="alpine")
    d = svc.to_dict()
    assert d == {"image": "alpine"}
    for k in ("command", "environment", "volumes", "ports", "shm_size",
              "restart", "stop_grace_period", "ulimits", "labels", "deploy"):
        assert k not in d


# -- ComposeBuilder rendering --------------------------------------------


def test_builder_render_produces_valid_yaml():
    svc = ComposeService(name="svc", image="alpine")
    text = ComposeBuilder().add_service(svc).render()
    parsed = yaml.safe_load(text)
    assert parsed == {"services": {"svc": {"image": "alpine"}}}


def test_builder_patch_updates_existing_service():
    svc = ComposeService(name="svc", image="alpine")
    builder = ComposeBuilder().add_service(svc)
    builder.patch("svc", shm_size="512m", restart="unless-stopped")
    d = builder.to_dict()["services"]["svc"]
    assert d["shm_size"] == "512m"
    assert d["restart"] == "unless-stopped"


def test_builder_patch_rejects_unknown_field():
    builder = ComposeBuilder().add_service(ComposeService(name="svc", image="alpine"))
    with pytest.raises(AttributeError):
        builder.patch("svc", not_a_field=True)


def test_builder_merge_volumes_is_idempotent():
    """Re-applying the same volume list must not produce duplicates."""
    builder = ComposeBuilder().add_service(ComposeService(name="svc", image="alpine"))
    vol = ["/host:/ctr"]
    builder.merge_volumes("svc", vol).merge_volumes("svc", vol)
    assert builder.services["svc"].volumes == ["/host:/ctr"]


def test_builder_merge_environment_is_additive():
    """Successive merges combine into one dict (later wins on conflict)."""
    builder = ComposeBuilder().add_service(ComposeService(name="svc", image="alpine"))
    builder.merge_environment("svc", {"A": "1"})
    builder.merge_environment("svc", {"B": "2", "A": "3"})
    assert builder.services["svc"].environment == {"A": "3", "B": "2"}


def test_builder_declare_volume_emits_top_level_volumes():
    """A declared named volume appears under a top-level ``volumes:`` key."""
    import yaml

    builder = ComposeBuilder().add_service(ComposeService(name="svc", image="alpine"))
    builder.declare_volume("sanity_home")
    doc = yaml.safe_load(builder.render())
    assert "volumes" in doc
    assert "sanity_home" in doc["volumes"]
    # A config-less volume renders as a null value (compose treats it as
    # a default docker-managed volume).
    assert doc["volumes"]["sanity_home"] is None


def test_builder_no_volumes_key_when_none_declared():
    """``volumes:`` must be absent entirely when no named volume is declared."""
    builder = ComposeBuilder().add_service(ComposeService(name="svc", image="alpine"))
    assert "volumes" not in builder.to_dict()


def test_builder_declare_volume_idempotent():
    """Re-declaring the same volume name does not duplicate it."""
    builder = ComposeBuilder().add_service(ComposeService(name="svc", image="alpine"))
    builder.declare_volume("v").declare_volume("v")
    assert list(builder.volumes) == ["v"]


def test_builder_set_deploy_resources_quotes_numeric_strings():
    """cpus='1.5' must become a quoted YAML string, not a float."""
    builder = ComposeBuilder().add_service(ComposeService(name="svc", image="alpine"))
    builder.set_deploy_resources("svc", cpus="1.5", memory="2g")
    text = builder.render()
    # cpus is numeric-looking -> PyYAML auto-quotes it
    assert "cpus: '1.5'" in text
    # memory is a docker size string ('2g') -> safe to emit bare
    assert "memory: 2g" in text
    # Round-trip still gives string values
    parsed = yaml.safe_load(text)
    limits = parsed["services"]["svc"]["deploy"]["resources"]["limits"]
    assert limits["cpus"] == "1.5"
    assert limits["memory"] == "2g"


def test_builder_set_deploy_resources_noop_when_both_none():
    builder = ComposeBuilder().add_service(ComposeService(name="svc", image="alpine"))
    builder.set_deploy_resources("svc", cpus=None, memory=None)
    assert builder.services["svc"].deploy is None


# -- ${VAR:-default} preservation ----------------------------------------


def test_var_expansion_strings_preserved_verbatim():
    """Critical: shell-style ${VAR:-default} must survive yaml.safe_dump."""
    svc = ComposeService(
        name="svc",
        image="${SANITY_IMAGE:-default:tag}",
        environment={"HOST_USER": "${HOST_USER:-developer}"},
        volumes=["${WORKSPACE_DIR:-./workspace}:/home/${HOST_USER:-developer}/workspace"],
        ports=["${SSH_HOST_PORT:-2222}:22"],
    )
    text = ComposeBuilder().add_service(svc).render()
    assert "${SANITY_IMAGE:-default:tag}" in text
    assert "HOST_USER=${HOST_USER:-developer}" in text
    assert "${WORKSPACE_DIR:-./workspace}:/home/${HOST_USER:-developer}/workspace" in text
    assert "${SSH_HOST_PORT:-2222}:22" in text
    # Round-trip preserves them too.
    parsed = yaml.safe_load(text)
    assert parsed["services"]["svc"]["image"] == "${SANITY_IMAGE:-default:tag}"


def test_shm_size_512m_emitted_bare_but_remains_string():
    svc = ComposeService(name="svc", image="alpine", shm_size="512m")
    text = ComposeBuilder().add_service(svc).render()
    assert "shm_size: 512m" in text
    parsed = yaml.safe_load(text)
    assert parsed["services"]["svc"]["shm_size"] == "512m"


# -- snapshot via the CLI helpers ----------------------------------------


def _load_cli():
    """Compatibility shim: return a façade exposing the legacy
    ``generate_compose_for_tag`` / ``generate_resource_compose`` callables
    from the new :mod:`sanity_gravity.compose.generators` location.
    """
    from sanity_gravity.compose import generators as cg  # noqa: E402
    return cg


def test_snapshot_generate_compose_for_tag_kasm(tmp_path, monkeypatch):
    """End-to-end: generate_compose_for_tag('ag-xfce-kasm') produces a file
    whose YAML payload contains every expected key, structurally."""
    monkeypatch.chdir(tmp_path)
    cli = _load_cli()
    output_file, service_name = cli.generate_compose_for_tag("ag-xfce-kasm")

    assert service_name == "ag-xfce-kasm"
    assert os.path.exists(output_file)

    parsed = yaml.safe_load(Path(output_file).read_text())
    svc = parsed["services"]["ag-xfce-kasm"]

    # image is the SANITY_IMAGE_* placeholder.
    assert svc["image"] == "${SANITY_IMAGE_AG_XFCE_KASM:-sanity-gravity:ag-xfce-kasm}"
    # environment is list-form with HOST_USER and friends.
    env = svc["environment"]
    assert "HOST_USER=${HOST_USER:-developer}" in env
    assert "HOST_UID=${HOST_UID:-1000}" in env
    # ports include both SSH and Kasm mappings.
    assert "${SSH_HOST_PORT:-2222}:22" in svc["ports"]
    assert "${KASM_PORT:-8444}:8444" in svc["ports"]
    # Kasm-specific compose settings are present.
    assert svc["shm_size"] == "512m"
    assert svc["restart"] == "unless-stopped"
    assert svc["stop_grace_period"] == "30s"
    # ulimits + labels carried over from the legacy template.
    assert svc["cap_drop"] == ["ALL"]
    assert "CHOWN" in svc["cap_add"]
    assert "SYS_CHROOT" in svc["cap_add"]
    assert svc["pids_limit"] == 2048
    assert svc["ulimits"] == {
        "nofile": {"soft": 65536, "hard": 65536},
        "core": {"soft": 0, "hard": 0},
    }
    assert svc["labels"] == {
        "sanity.gravity.managed": "true",
        "sanity.gravity.home-volume": "true",
    }
    # Persistent-home model: the sanity_home named volume is mounted at
    # the home dir, the workspace bind nested inside, and the volume is
    # declared at the top level.
    assert svc["volumes"] == [
        "sg_ag-xfce-kasm:/home/${HOST_USER:-developer}",
        "${WORKSPACE_DIR:-./workspace}:/home/${HOST_USER:-developer}/workspace",
    ]
    assert "sg_ag-xfce-kasm" in parsed["volumes"]


def test_snapshot_generate_resource_compose(tmp_path, monkeypatch):
    """generate_resource_compose writes deploy.resources.limits correctly."""
    monkeypatch.chdir(tmp_path)
    cli = _load_cli()
    output_file = cli.generate_resource_compose("1.5", "2g", "ag-xfce-kasm")
    assert output_file is not None
    parsed = yaml.safe_load(Path(output_file).read_text())
    limits = parsed["services"]["ag-xfce-kasm"]["deploy"]["resources"]["limits"]
    assert limits == {"cpus": "1.5", "memory": "2g"}


def test_snapshot_generate_resource_compose_returns_none_when_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cli = _load_cli()
    assert cli.generate_resource_compose(None, None, "svc") is None
