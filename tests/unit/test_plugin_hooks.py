"""Tests for plugin ``hooks.py`` loading + symmetric manifest merging.

Covers Q2: any plugin folder may ship a ``hooks.py`` next to its
``manifest.toml`` to register lifecycle callbacks via ``@on(Phase.X)``.
The registry imports each module once at scan time; subsequent
``register_builtin_*_hooks`` calls splice the module-level default bus
into the per-verb bus so the plugin hooks fire alongside the builtins.

Also covers the merge of agent / desktop / connector contributions in
``generate_compose_for_tag`` and ``announce`` — symmetric manifest
schema means any kind may declare ``[ports]`` / ``[compose]`` /
``[environment]`` / ``[announce]``.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from sanity_gravity.core.eventbus import (
    EventBus,
    get_default_bus,
)
from sanity_gravity.domain.phase import Phase
from sanity_gravity.plugins.registry import (
    PluginRegistry,
    reset_default_registry,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write_manifest(slug_dir: Path, slug: str, kind: str, body_extra: str = "") -> None:
    slug_dir.mkdir(parents=True, exist_ok=True)
    (slug_dir / "manifest.toml").write_text(
        f'[plugin]\nslug = "{slug}"\nname = "{slug}"\n'
        f'kind = "{kind}"\napi_version = "1"\n'
        f'[build]\ndockerfile = "Dockerfile"\n'
        f'{body_extra}'
    )
    (slug_dir / "Dockerfile").write_text("FROM scratch\n")


def _write_hooks(slug_dir: Path, body: str) -> None:
    (slug_dir / "hooks.py").write_text(textwrap.dedent(body))


@pytest.fixture(autouse=True)
def _isolated_default_state():
    """Each test gets a clean default registry + default bus."""
    reset_default_registry()
    yield
    reset_default_registry()


# ---------------------------------------------------------------------------
# hooks.py loading
# ---------------------------------------------------------------------------


def test_hooks_py_registers_callback_on_default_bus(tmp_path):
    """A plugin's hooks.py @on subscription appears on the default bus."""
    _write_manifest(tmp_path / "agents" / "demo", "demo", "agent")
    _write_hooks(
        tmp_path / "agents" / "demo",
        """
        from sanity_gravity.core.eventbus import on
        from sanity_gravity.domain.phase import Phase

        @on(Phase.UP_ANNOUNCE, name="demo_marker")
        def _demo(ctx):
            ctx.fired = True
        """,
    )
    PluginRegistry.from_dir(tmp_path)

    hooks = get_default_bus().hooks_for(Phase.UP_ANNOUNCE)
    assert any(h.name == "demo_marker" for h in hooks), hooks


def test_hooks_py_fires_during_up_announce(tmp_path, monkeypatch):
    """Splicing the default bus into a per-verb bus runs plugin hooks."""
    _write_manifest(tmp_path / "agents" / "demo", "demo", "agent")
    _write_hooks(
        tmp_path / "agents" / "demo",
        """
        from sanity_gravity.core.eventbus import on
        from sanity_gravity.domain.phase import Phase

        @on(Phase.UP_ANNOUNCE)
        def _record(ctx):
            ctx.captured.append("plugin-fired")
        """,
    )
    PluginRegistry.from_dir(tmp_path)

    bus = EventBus()
    get_default_bus().merge_into(bus)

    class _Ctx:
        captured: list[str] = []

    ctx = _Ctx()
    ctx.captured = []
    bus.publish(Phase.UP_ANNOUNCE, ctx)
    assert ctx.captured == ["plugin-fired"]


def test_syntax_error_in_hooks_py_raises_with_path(tmp_path):
    """A broken hooks.py surfaces the offending plugin's path.

    The wrapper is a :class:`ManifestError`; the original SyntaxError is
    chained through ``__cause__`` so the plugin's call site is still
    available in the traceback.
    """
    from sanity_gravity.plugins.manifest import ManifestError

    _write_manifest(tmp_path / "agents" / "broken", "broken", "agent")
    _write_hooks(tmp_path / "agents" / "broken", "this is not valid python !!!\n")

    with pytest.raises(ManifestError) as excinfo:
        PluginRegistry.from_dir(tmp_path)
    assert "broken" in str(excinfo.value)
    assert "hooks.py" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, SyntaxError)


def test_oserror_in_hooks_py_does_not_break_reraise(tmp_path):
    """Plugin import errors whose ctor isn't ``(str)`` are wrapped, not re-built.

    Regression: previously the loader did ``raise type(exc)(msg)``; for
    OSError-family exceptions this either crashed (TypeError on ctor) or
    silently dropped fields. The wrapper makes the failure mode boring.
    """
    from sanity_gravity.plugins.manifest import ManifestError

    _write_manifest(tmp_path / "agents" / "ose", "ose", "agent")
    _write_hooks(
        tmp_path / "agents" / "ose",
        "import errno\nraise OSError(errno.EACCES, 'denied')\n",
    )
    with pytest.raises(ManifestError) as excinfo:
        PluginRegistry.from_dir(tmp_path)
    assert "ose" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, OSError)


def test_plugin_without_hooks_py_loads_normally(tmp_path):
    """A plugin lacking hooks.py works exactly as before."""
    _write_manifest(tmp_path / "agents" / "noh", "noh", "agent")
    reg = PluginRegistry.from_dir(tmp_path)
    assert "noh" in reg.agents
    assert reg._loaded_hook_modules == []


def test_hooks_py_idempotent_across_repeated_load(tmp_path):
    """Re-importing the same hooks.py without reset is a no-op."""
    _write_manifest(tmp_path / "agents" / "once", "once", "agent")
    _write_hooks(
        tmp_path / "agents" / "once",
        """
        from sanity_gravity.core.eventbus import on
        from sanity_gravity.domain.phase import Phase

        @on(Phase.UP_ANNOUNCE)
        def _h(ctx): pass
        """,
    )
    PluginRegistry.from_dir(tmp_path)
    PluginRegistry.from_dir(tmp_path)  # second scan must not double-register

    hooks = get_default_bus().hooks_for(Phase.UP_ANNOUNCE)
    assert len(hooks) == 1


def test_reset_default_registry_clears_hook_modules_and_bus():
    """Reset must drop sys.modules entries and clear the default bus."""
    from sanity_gravity.plugins.registry import default_registry
    reg = default_registry()
    # Builtin kasm hook should now be loaded:
    assert any("kasm" in m for m in reg._loaded_hook_modules)
    assert get_default_bus().hooks_for(Phase.UP_ANNOUNCE)

    reset_default_registry()
    assert get_default_bus().hooks_for(Phase.UP_ANNOUNCE) == []


# ---------------------------------------------------------------------------
# Symmetric manifest schema → compose merge
# ---------------------------------------------------------------------------


def test_agent_environment_merges_into_compose(monkeypatch, tmp_path):
    """An agent's [environment] flows into generate_compose_for_tag output."""
    # Build a tiny synthetic plugin tree: ag-min-stub (3 plugins).
    _write_manifest(
        tmp_path / "agents" / "ag",
        "ag",
        "agent",
        '[capabilities]\nrequires = ["display"]\n'
        '[environment]\nOPENAI_API_KEY = "${OPENAI_API_KEY:-}"\n',
    )
    _write_manifest(
        tmp_path / "desktops" / "xfce",
        "xfce",
        "desktop",
        '[capabilities]\nprovides = ["display"]\n',
    )
    _write_manifest(
        tmp_path / "connectors" / "stub",
        "stub",
        "connector",
        '[capabilities]\nrequires = ["display"]\n'
        '[ports.http]\ninternal = 8000\ndefault = 8000\nenv_var = "STUB_PORT"\n'
        '[compose]\nshm_size = "256m"\n',
    )

    # Re-route the global registry to this tree.
    reset_default_registry()
    from sanity_gravity.plugins import registry as reg_mod
    reg_mod._DEFAULT = PluginRegistry.from_dir(tmp_path)

    monkeypatch.chdir(tmp_path)
    from sanity_gravity.compose import generators as cg
    output_file, _ = cg.generate_compose_for_tag("ag-xfce-stub")

    import yaml
    parsed = yaml.safe_load(Path(output_file).read_text())
    svc = parsed["services"]["ag-xfce-stub"]
    assert "OPENAI_API_KEY=${OPENAI_API_KEY:-}" in svc["environment"]
    assert "${STUB_PORT:-8000}:8000" in svc["ports"]
    assert svc["shm_size"] == "256m"


def test_desktop_compose_overrides_connector_last_write_wins(monkeypatch, tmp_path):
    """Desktop's [compose] field overrides connector's (last-write-wins)."""
    _write_manifest(tmp_path / "agents" / "ag", "ag", "agent",
                    '[capabilities]\nrequires = ["display"]\n')
    _write_manifest(
        tmp_path / "desktops" / "xfce",
        "xfce",
        "desktop",
        '[capabilities]\nprovides = ["display"]\n'
        '[compose]\nshm_size = "1g"\n',
    )
    _write_manifest(
        tmp_path / "connectors" / "stub",
        "stub",
        "connector",
        '[capabilities]\nrequires = ["display"]\n'
        '[ports.http]\ninternal = 8000\ndefault = 8000\nenv_var = "STUB_PORT"\n'
        '[compose]\nshm_size = "256m"\nrestart = "always"\n',
    )

    reset_default_registry()
    from sanity_gravity.plugins import registry as reg_mod
    reg_mod._DEFAULT = PluginRegistry.from_dir(tmp_path)

    monkeypatch.chdir(tmp_path)
    from sanity_gravity.compose import generators as cg
    output_file, _ = cg.generate_compose_for_tag("ag-xfce-stub")

    import yaml
    svc = yaml.safe_load(Path(output_file).read_text())["services"]["ag-xfce-stub"]
    # Desktop overrides shm_size; connector's restart survives.
    assert svc["shm_size"] == "1g"
    assert svc["restart"] == "always"
