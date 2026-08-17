"""Tests for the plugin tier policy (official / community / deprecated).

Tier semantics:

- ``official``   - included in the CI build/verify and release publish
  matrix (the status quo for undeclared manifests).
- ``community``  - tag is valid and locally buildable, but absent from
  every CI matrix and never published to GHCR.
- ``deprecated`` - tag still parses (lifecycle/clean/status keep working
  for existing containers); local build/up print a warning but proceed;
  absent from every CI matrix.

CI enumerates its matrices from a single source (``sanity-cli list
--json`` for the publish/scan/test matrices, ``sanity-cli build all``
for the build set), so the filter is pinned at that source:
``PluginRegistry.valid_tags(tiers=...)`` feeding ``OFFICIAL_TAGS``.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest


from sanity_gravity.domain.tags import Tag
from sanity_gravity.plugins.registry import PluginRegistry

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _write_manifest(
    slug_dir: Path,
    slug: str,
    kind: str,
    tier: str | None = None,
    provides: tuple[str, ...] = (),
    requires: tuple[str, ...] = (),
) -> None:
    slug_dir.mkdir(parents=True, exist_ok=True)
    tier_line = f'tier = "{tier}"\n' if tier else ""
    provides_toml = ", ".join(f'"{c}"' for c in provides)
    requires_toml = ", ".join(f'"{c}"' for c in requires)
    (slug_dir / "manifest.toml").write_text(
        f'[plugin]\nslug = "{slug}"\nname = "{slug}"\n'
        f'kind = "{kind}"\napi_version = "1"\n{tier_line}'
        f"[capabilities]\nprovides = [{provides_toml}]\n"
        f"requires = [{requires_toml}]\n"
        f'[build]\ndockerfile = "Dockerfile"\n'
    )
    (slug_dir / "Dockerfile").write_text("FROM scratch\n")


@pytest.fixture
def tiered_registry(tmp_path) -> PluginRegistry:
    """Two agents (official + deprecated), one community connector."""
    _write_manifest(tmp_path / "agents" / "aa", "aa", "agent")
    _write_manifest(tmp_path / "agents" / "dd", "dd", "agent", tier="deprecated")
    _write_manifest(tmp_path / "desktops" / "none", "none", "desktop")
    _write_manifest(tmp_path / "connectors" / "ssh", "ssh", "connector")
    _write_manifest(
        tmp_path / "connectors" / "co", "co", "connector", tier="community"
    )
    return PluginRegistry.from_dir(tmp_path)


# ---------------------------------------------------------------------------
# Registry: tag tier resolution.
# ---------------------------------------------------------------------------


class TestTagTier:
    def test_all_official_plugins_yield_official_tag(self, tiered_registry):
        assert tiered_registry.tag_tier(Tag("aa", "none", "ssh")) == "official"

    def test_deprecated_plugin_taints_the_tag(self, tiered_registry):
        assert tiered_registry.tag_tier(Tag("dd", "none", "ssh")) == "deprecated"

    def test_community_plugin_taints_the_tag(self, tiered_registry):
        assert tiered_registry.tag_tier(Tag("aa", "none", "co")) == "community"

    def test_deprecated_outranks_community(self, tiered_registry):
        """The most restrictive tier across the three plugins wins."""
        assert tiered_registry.tag_tier(Tag("dd", "none", "co")) == "deprecated"


# ---------------------------------------------------------------------------
# Registry: enumeration filter.
# ---------------------------------------------------------------------------


class TestValidTagsTierFilter:
    def test_default_includes_all_tiers(self, tiered_registry):
        """Lifecycle/clean/status resolve tags via the unfiltered view, so
        deprecated tags must stay enumerable by default."""
        tags = tiered_registry.valid_tags()
        assert Tag("dd", "none", "ssh") in tags
        assert Tag("aa", "none", "co") in tags

    def test_official_filter_excludes_community_and_deprecated(
        self, tiered_registry
    ):
        tags = tiered_registry.valid_tags(tiers=("official",))
        assert tags == [Tag("aa", "none", "ssh")]

    def test_filter_can_admit_multiple_tiers(self, tiered_registry):
        tags = tiered_registry.valid_tags(tiers=("official", "community"))
        assert Tag("aa", "none", "ssh") in tags
        assert Tag("aa", "none", "co") in tags
        assert Tag("dd", "none", "ssh") not in tags


# ---------------------------------------------------------------------------
# CLI projections: OFFICIAL_TAGS / list --json.
# ---------------------------------------------------------------------------


class TestCliEnumeration:
    def test_official_tags_subset_of_valid_tags(self):
        from sanity_gravity.cli.registry import OFFICIAL_TAGS, VALID_TAGS

        assert set(OFFICIAL_TAGS) <= set(VALID_TAGS)

    def test_gc_tags_left_the_matrix_but_stay_valid(self):
        """gc (Gemini CLI) is deprecated: all four gc-* tags leave the
        CI/publish matrix while remaining parseable for lifecycle."""
        from sanity_gravity.cli.registry import (
            OFFICIAL_TAGS,
            VALID_TAGS,
            parse_tag,
            tag_tier,
        )

        gc_tags = [t for t in VALID_TAGS if parse_tag(t)[0] == "gc"]
        assert len(gc_tags) == 4
        assert not any(parse_tag(t)[0] == "gc" for t in OFFICIAL_TAGS)
        # Everything else is untouched by gc's retirement.
        assert set(VALID_TAGS) - set(gc_tags) == set(OFFICIAL_TAGS)
        for t in gc_tags:
            assert tag_tier(t) == "deprecated"
            parse_tag(t)  # must not raise

    def test_list_json_emits_official_tags_only(self, capsys):
        """``list --json`` is the CI matrix source; it must enumerate the
        official tier only."""
        from sanity_gravity.verbs import status as status_mod

        with patch.object(status_mod, "OFFICIAL_TAGS", ["aa-none-ssh"]), \
             patch.object(
                 status_mod, "VALID_TAGS", ["aa-none-ssh", "dd-none-ssh"]
             ):
            status_mod.list_variants(argparse.Namespace(json_output=True))
        assert json.loads(capsys.readouterr().out) == ["aa-none-ssh"]

    def test_list_human_output_marks_non_official_tags(self, capsys):
        from sanity_gravity.verbs import status as status_mod

        def fake_tier(tag):
            return {"dd-none-ssh": "deprecated", "co-none-ssh": "community"}.get(
                tag, "official"
            )

        with patch.object(
                 status_mod, "VALID_TAGS",
                 ["aa-none-ssh", "dd-none-ssh", "co-none-ssh"],
             ), \
             patch.object(status_mod, "tag_tier", side_effect=fake_tier):
            status_mod.list_variants(argparse.Namespace(json_output=False))
        out = capsys.readouterr().out
        assert "deprecated" in out
        assert "community" in out


# ---------------------------------------------------------------------------
# Build enumeration: ``build all`` follows the official set.
# ---------------------------------------------------------------------------


def _layer_name(node):
    """Rendered layer name of a PlanNode, via the one grammar owner."""
    from sanity_gravity.domain.naming import Naming

    return Naming.layer(node.layer.kind, node.layer.detail)


class TestBuildAllTierFilter:
    def _run_build(self, **ctx_kwargs):
        from sanity_gravity.core.eventbus import EventBus
        from sanity_gravity.core.orchestrator import (
            BuildContext,
            Orchestrator,
            _BUILD_PHASES,
        )
        from sanity_gravity.core.reporter import Reporter
        from sanity_gravity.hooks.build import register_builtin_build_hooks

        bus = EventBus()
        register_builtin_build_hooks(bus)
        ctx = BuildContext(
            reporter=Reporter(sinks=[], run_id="test"),
            dry_run=True,
            **ctx_kwargs,
        )
        Orchestrator(bus, ctx.reporter).run(_BUILD_PHASES, ctx)
        return ctx

    def _run_build_all(self):
        return self._run_build(targets=["all"])

    def test_build_all_plans_only_official_tags(self, monkeypatch):
        import sanity_gravity.hooks.build as build_hooks

        monkeypatch.setattr(build_hooks, "OFFICIAL_TAGS", ["cc-none-ssh"])
        ctx = self._run_build_all()
        planned = [_layer_name(node) for node in ctx.plan]
        # Finals restricted to the official set; intermediates follow.
        assert [n for n in planned if not n.startswith("_")] == ["cc-none-ssh"]
        assert set(n for n in planned if n.startswith("_")) == {
            "_base", "_base-none", "_cc-none",
        }

    def test_build_all_finals_match_official_tags(self):
        from sanity_gravity.cli.registry import OFFICIAL_TAGS

        ctx = self._run_build_all()
        finals = [
            _layer_name(node) for node in ctx.plan
            if not _layer_name(node).startswith("_")
        ]
        assert finals == list(OFFICIAL_TAGS)

    def test_layer_desktop_follows_official_tier(self, monkeypatch):
        import sanity_gravity.hooks.build as build_hooks

        monkeypatch.setattr(build_hooks, "OFFICIAL_TAGS", ["cc-none-ssh"])
        ctx = self._run_build(targets=[], layer_target="desktop")
        planned = [_layer_name(node) for node in ctx.plan]
        assert "_base-none" in planned
        # xfce exists in the registry, but no official tag references it
        # in this scenario: the default enumeration must skip it, same
        # as the agent / connector layer branches.
        assert "_base-xfce" not in planned

    def test_layer_desktop_explicit_target_ignores_tier(self, monkeypatch):
        import sanity_gravity.hooks.build as build_hooks

        monkeypatch.setattr(build_hooks, "OFFICIAL_TAGS", ["cc-none-ssh"])
        ctx = self._run_build(
            targets=[], layer_target="desktop", layer_target_specific="xfce",
        )
        planned = [_layer_name(node) for node in ctx.plan]
        assert "_base-xfce" in planned


# ---------------------------------------------------------------------------
# Deprecation warnings on local build / up (warn, never block).
# ---------------------------------------------------------------------------


class TestDeprecationWarnings:
    def test_build_explicit_deprecated_target_warns_but_proceeds(
        self, monkeypatch
    ):
        monkeypatch.chdir(_REPO_ROOT)
        from sanity_gravity.core.reporter import Reporter
        from sanity_gravity.verbs import build as build_mod

        args = argparse.Namespace(
            no_cache=False,
            list_intermediates=False,
            layer=None,
            layer_target=None,
            variant=["cc-none-ssh"],
            dry_run=True,
            json_output=False,
            reporter=Reporter(sinks=[], run_id="test"),
        )
        with patch("sanity_gravity.cli.registry.tag_tier",
                   return_value="deprecated"), \
             patch.object(build_mod, "print_warning") as warn:
            build_mod.build(args)  # must not raise / exit
        assert warn.called
        assert "deprecated" in warn.call_args[0][0]

    def _up_args(self, tmp_path, reporter):
        return argparse.Namespace(
            variant="cc-none-ssh",
            skip_check=True,
            workspace=str(tmp_path / "ws"),
            name="proj-test",
            ssh_port="2222", kasm_port="8444",
            vnc_port="5901", novnc_port="6901",
            password="pw", cpus=None, memory=None, image=None,
            reporter=reporter,
            dry_run=True,
        )

    def test_up_deprecated_tag_warns_but_proceeds(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from sanity_gravity.core.reporter import build_default_reporter
        from sanity_gravity.verbs import up as up_mod

        reporter = build_default_reporter(
            log_format="text", base=tmp_path / "runs"
        )
        try:
            with patch("sanity_gravity.cli.registry.tag_tier",
                       return_value="deprecated"), \
                 patch.object(up_mod, "print_warning") as warn, \
                 patch("sanity_gravity.verbs.up.get_uid_gid_user",
                       return_value=(1000, 1000, "u")):
                up_mod.up(self._up_args(tmp_path, reporter))
        finally:
            reporter.close()
        deprecation_calls = [
            c for c in warn.call_args_list if "deprecated" in c[0][0]
        ]
        assert deprecation_calls, "up must warn about a deprecated tag"

    def test_up_community_tag_is_quiet(self, tmp_path, monkeypatch):
        """Community tags build/up without noise; only deprecated warns."""
        monkeypatch.chdir(tmp_path)
        from sanity_gravity.core.reporter import build_default_reporter
        from sanity_gravity.verbs import up as up_mod

        reporter = build_default_reporter(
            log_format="text", base=tmp_path / "runs"
        )
        try:
            with patch("sanity_gravity.cli.registry.tag_tier",
                       return_value="community"), \
                 patch.object(up_mod, "print_warning") as warn, \
                 patch("sanity_gravity.verbs.up.get_uid_gid_user",
                       return_value=(1000, 1000, "u")):
                up_mod.up(self._up_args(tmp_path, reporter))
        finally:
            reporter.close()
        assert not any(
            "deprecated" in c[0][0] for c in warn.call_args_list
        )
