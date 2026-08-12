"""Tests that ``reset_default_registry`` + repeat scan is idempotent.

Test isolation depends on this: a stale ``hooks.py`` module left in
``sys.modules`` between tests would cause one test's ``@on``
subscriptions to fire in the next test's scan. The fixture in
``test_plugin_hooks.py`` already calls ``reset_default_registry``;
these tests pin the contract.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


from sanity_gravity.core.eventbus import get_default_bus
from sanity_gravity.domain.phase import Phase
from sanity_gravity.plugins.registry import (
    PluginRegistry,
    reset_default_registry,
)


def _write_manifest(slug_dir: Path, slug: str, kind: str) -> None:
    slug_dir.mkdir(parents=True, exist_ok=True)
    (slug_dir / "manifest.toml").write_text(
        f'[plugin]\nslug = "{slug}"\nname = "{slug}"\n'
        f'kind = "{kind}"\napi_version = "1"\n'
        f'[build]\ndockerfile = "Dockerfile"\n'
    )
    (slug_dir / "Dockerfile").write_text("FROM scratch\n")


def _write_hooks(slug_dir: Path, body: str) -> None:
    (slug_dir / "hooks.py").write_text(body)


@pytest.fixture(autouse=True)
def _isolated_default():
    reset_default_registry()
    yield
    reset_default_registry()


class TestRegistryIdempotence:
    def test_two_scans_same_dir_yield_same_slug_set(self, tmp_path):
        _write_manifest(tmp_path / "agents" / "ag", "ag", "agent")
        _write_manifest(tmp_path / "agents" / "gc", "gc", "agent")
        _write_manifest(tmp_path / "desktops" / "xfce", "xfce", "desktop")
        _write_manifest(tmp_path / "connectors" / "ssh", "ssh", "connector")

        reg1 = PluginRegistry.from_dir(tmp_path)
        agents1 = set(reg1.agents)
        desktops1 = set(reg1.desktops)
        connectors1 = set(reg1.connectors)

        reg2 = PluginRegistry.from_dir(tmp_path)
        assert set(reg2.agents) == agents1
        assert set(reg2.desktops) == desktops1
        assert set(reg2.connectors) == connectors1

    def test_reset_then_rescan_yields_same_set(self, tmp_path):
        _write_manifest(tmp_path / "agents" / "ag", "ag", "agent")
        _write_manifest(tmp_path / "desktops" / "xfce", "xfce", "desktop")
        _write_manifest(tmp_path / "connectors" / "ssh", "ssh", "connector")

        reg1 = PluginRegistry.from_dir(tmp_path)
        snapshot1 = (set(reg1.agents), set(reg1.desktops), set(reg1.connectors))

        reset_default_registry()

        reg2 = PluginRegistry.from_dir(tmp_path)
        snapshot2 = (set(reg2.agents), set(reg2.desktops), set(reg2.connectors))

        assert snapshot1 == snapshot2

    def test_reset_clears_default_bus_subscriptions(self, tmp_path):
        """A plugin's ``@on`` subscription registered against the
        default bus must NOT survive a ``reset_default_registry`` —
        otherwise a stale hook fires in the next test's scan."""
        _write_manifest(tmp_path / "agents" / "iso", "iso", "agent")
        _write_hooks(
            tmp_path / "agents" / "iso",
            "from sanity_gravity.core.eventbus import on\n"
            "from sanity_gravity.domain.phase import Phase\n"
            "@on(Phase.UP_ANNOUNCE)\n"
            "def _h(ctx):\n    pass\n",
        )

        PluginRegistry.from_dir(tmp_path)
        before_reset = len(get_default_bus().hooks_for(Phase.UP_ANNOUNCE))
        assert before_reset >= 1

        reset_default_registry()
        after_reset = len(get_default_bus().hooks_for(Phase.UP_ANNOUNCE))
        assert after_reset == 0

    def test_module_reimport_after_reset(self, tmp_path):
        """After reset, re-scanning the same dir re-executes the
        plugin's hooks.py (so the module's @on decorators run again)."""
        _write_manifest(tmp_path / "agents" / "iso", "iso", "agent")
        _write_hooks(
            tmp_path / "agents" / "iso",
            "from sanity_gravity.core.eventbus import on\n"
            "from sanity_gravity.domain.phase import Phase\n"
            "@on(Phase.UP_ANNOUNCE)\n"
            "def _h(ctx):\n    pass\n",
        )

        PluginRegistry.from_dir(tmp_path)
        first = len(get_default_bus().hooks_for(Phase.UP_ANNOUNCE))

        reset_default_registry()
        PluginRegistry.from_dir(tmp_path)
        second = len(get_default_bus().hooks_for(Phase.UP_ANNOUNCE))

        # Same number of subscriptions — re-scan re-registered exactly
        # what the first scan had. No "double registration" because
        # reset clears the default bus first.
        assert second == first
