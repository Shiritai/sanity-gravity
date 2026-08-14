"""Plugin registry: discover and index manifest-driven plugins.

A registry walks ``plugins/<kind>/<slug>/manifest.toml`` once at startup
and stores the parsed :class:`~manifest.PluginManifest` objects in three
kind-keyed dicts. Other components (CLI tag parsing, build-chain
resolver, compose hook, announce hook) consult the registry via small
typed accessors instead of hardcoded ``AGENTS`` / ``DESKTOPS`` /
``CONNECTORS`` literals.

Discovery is filesystem-based and builtin-only: there is no entry-point
support and no remote loading. Adding a new dimension is ``mkdir
plugins/<kind>/<slug>/`` + ``manifest.toml`` + ``Dockerfile``.

If a plugin needs to react to a lifecycle phase the manifest can't
express (e.g. emit an extra info line after announce, or run a
post-provision step), it can drop a ``hooks.py`` next to its
``manifest.toml``. The registry imports each ``hooks.py`` once at
startup; the module is expected to use the ``@on(Phase.X)`` decorator
from :mod:`sanity_gravity.core.eventbus` to subscribe callbacks. Each
verb's ``register_builtin_*_hooks`` then merges those subscriptions
into the verb's per-run bus.

Loaded modules are placed in :data:`sys.modules` under the synthetic
name ``sanity_gravity.plugins.<kind>.<slug>.hooks`` so re-import is
idempotent. A syntax error or import-time exception in a plugin's
``hooks.py`` is re-raised with the offending file path prepended — never
silently skipped. Plugin authors are trusted: hooks run with full
Python privileges (consistent with the no-remote-URL anti-pattern in
the design doc; sandboxing is out of scope here).
"""
from __future__ import annotations

import importlib.util
import sys
from collections.abc import Collection
from pathlib import Path

from sanity_gravity.domain.capability import CapabilityConflictError, solve
from sanity_gravity.domain.tags import DEFAULT_BASE_IMAGE, Tag
from sanity_gravity.plugins.manifest import (
    TIERS,
    ManifestError,
    PluginManifest,
    load_manifest,
)


__all__ = ["PluginRegistry", "default_registry", "reset_default_registry"]


# Module-global tracking of every plugin hooks.py we've ever loaded — both
# the default registry and ad-hoc ``PluginRegistry.from_dir`` calls register
# here so ``reset_default_registry`` can drop them all from ``sys.modules``.
# Without this, a test-only registry built against a tmp dir would leak its
# hooks.py into the next scan (the synthetic dotted name is namespace-by-
# kind+slug, so a different tmp dir with the same slug looks identical).
_LOADED_HOOK_MODULES: set[str] = set()


_VALID_KINDS: tuple[str, ...] = ("base-image", "agent", "desktop", "connector")
_KIND_TO_PLURAL: dict[str, str] = {
    "base-image": "base-images",
    "agent": "agents",
    "desktop": "desktops",
    "connector": "connectors",
}


class PluginRegistry:
    """Four-keyed index of parsed plugin manifests.

    Attributes
    ----------
    base_images / agents / desktops / connectors:
        ``dict[slug -> PluginManifest]`` for that kind.
    root:
        Root of the plugin tree (e.g. ``plugins/``). Useful for callers
        that need to resolve relative manifest paths.
    """

    __slots__ = ("base_images", "agents", "desktops", "connectors", "root", "_loaded_hook_modules")

    def __init__(self, root: Path | None = None) -> None:
        self.base_images: dict[str, PluginManifest] = {}
        self.agents: dict[str, PluginManifest] = {}
        self.desktops: dict[str, PluginManifest] = {}
        self.connectors: dict[str, PluginManifest] = {}
        self.root = root
        # Synthetic dotted names of every hooks.py module this registry
        # has imported. ``reset_default_registry`` clears these from
        # ``sys.modules`` so the next scan re-executes the file.
        self._loaded_hook_modules: list[str] = []

    # -- construction ------------------------------------------------

    @classmethod
    def from_dir(cls, root: str | Path) -> "PluginRegistry":
        """Walk ``<root>/{agents,desktops,connectors}/<slug>/manifest.toml``.

        Each subdirectory missing a ``manifest.toml`` is silently skipped
        (it can host stale aux files mid-refactor); each *present* one is
        loaded and validated. Duplicate slugs within a kind raise.
        """
        r = Path(root)
        reg = cls(root=r)
        for kind in _VALID_KINDS:
            kind_dir = r / _KIND_TO_PLURAL[kind]
            if not kind_dir.is_dir():
                continue
            for slug_dir in sorted(kind_dir.iterdir()):
                if not slug_dir.is_dir():
                    continue
                manifest_path = slug_dir / "manifest.toml"
                if not manifest_path.is_file():
                    continue
                m = load_manifest(manifest_path)
                if m.kind != kind:
                    raise ManifestError(
                        f"{manifest_path}: kind '{m.kind}' does not match "
                        f"directory '{kind_dir.name}'"
                    )
                if m.slug != slug_dir.name:
                    raise ManifestError(
                        f"{manifest_path}: slug '{m.slug}' does not match "
                        f"directory '{slug_dir.name}'"
                    )
                bucket = reg._bucket(kind)
                if m.slug in bucket:
                    raise ManifestError(
                        f"{manifest_path}: duplicate slug '{m.slug}' for kind '{kind}'"
                    )
                bucket[m.slug] = m

                hooks_path = slug_dir / "hooks.py"
                if hooks_path.is_file():
                    mod_name = reg._load_hooks_module(kind, m.slug, hooks_path)
                    if mod_name is not None:
                        reg._loaded_hook_modules.append(mod_name)
        return reg

    @staticmethod
    def _load_hooks_module(kind: str, slug: str, hooks_path: Path) -> str | None:
        """Import ``hooks.py`` once, surfacing import-time errors clearly.

        The module is registered under a synthetic dotted name so a
        second scan (after :func:`reset_default_registry`) re-executes
        the file. If the file imports cleanly the ``@on`` decorators
        inside register against the module-level default EventBus,
        which each verb's ``register_builtin_*_hooks`` merges into its
        per-run bus.
        """
        mod_name = f"sanity_gravity.plugins.{kind}.{slug}.hooks"
        if mod_name in sys.modules:
            _LOADED_HOOK_MODULES.add(mod_name)
            return mod_name  # idempotent — already executed
        spec = importlib.util.spec_from_file_location(mod_name, hooks_path)
        if spec is None or spec.loader is None:
            raise ManifestError(
                f"{hooks_path}: failed to build import spec for plugin hooks"
            )
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException as exc:  # re-raise with provenance
            # Wrap in ManifestError rather than re-instantiating ``type(exc)``:
            # several builtin exception types (OSError, etc.) reject a single
            # string ctor, and ``type(exc)(msg)`` discards the original
            # traceback's call site even when it succeeds. ``raise … from exc``
            # preserves the chain so ``__cause__`` still points at the plugin.
            sys.modules.pop(mod_name, None)
            raise ManifestError(
                f"error loading plugin hooks at {hooks_path}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        _LOADED_HOOK_MODULES.add(mod_name)
        return mod_name

    # -- accessors ---------------------------------------------------

    def _bucket(self, kind: str) -> dict[str, PluginManifest]:
        if kind in ("base-image", "base_image", "base-images"):
            return self.base_images
        if kind == "agent":
            return self.agents
        if kind == "desktop":
            return self.desktops
        if kind == "connector":
            return self.connectors
        raise KeyError(f"unknown plugin kind: {kind!r}")

    def get(self, kind: str, slug: str) -> PluginManifest:
        """Return the manifest for ``(kind, slug)`` or raise ``KeyError``.

        ``kind`` accepts the singular form (``"agent"``).
        """
        bucket = self._bucket(kind)
        if slug not in bucket:
            raise KeyError(f"no {kind} plugin with slug {slug!r}")
        return bucket[slug]

    def all_slugs(self, kind: str) -> list[str]:
        """Slugs registered for ``kind``, in stable insertion order."""
        return list(self._bucket(kind).keys())

    def all_manifests(self) -> list[PluginManifest]:
        """Flat list of every registered manifest (base-images → agents → desktops → connectors)."""
        return [
            *self.base_images.values(),
            *self.agents.values(),
            *self.desktops.values(),
            *self.connectors.values(),
        ]

    # -- tag enumeration --------------------------------------------

    def tag_tier(self, tag: Tag) -> str:
        """Most restrictive tier among the tag's plugins."""
        manifests = [
            self.get("agent", tag.agent),
            self.get("desktop", tag.desktop),
            self.get("connector", tag.connector),
        ]
        if tag.base_image in self.base_images:
            manifests.append(self.get("base-image", tag.base_image))
        return max((m.tier for m in manifests), key=TIERS.index)

    def valid_tags(self, tiers: Collection[str] | None = None) -> list[Tag]:
        """All combos that satisfy capabilities.

        The default base (:data:`DEFAULT_BASE_IMAGE`) is always
        enumerated even before any ``base-image`` plugin is registered;
        registered non-default bases extend the matrix.
        """
        out: list[Tag] = []
        bases = [DEFAULT_BASE_IMAGE] + [
            b for b in self.base_images if b != DEFAULT_BASE_IMAGE
        ]
        for b in bases:
            for a in self.agents:
                for d in self.desktops:
                    for c in self.connectors:
                        tag = Tag(agent=a, desktop=d, connector=c, base_image=b)
                        try:
                            solve(tag, self)
                        except CapabilityConflictError:
                            continue
                        if tiers is not None and self.tag_tier(tag) not in tiers:
                            continue
                        out.append(tag)
        return out


# ---- module-level lazy default registry --------------------------------

_DEFAULT: PluginRegistry | None = None


def default_registry(root: str | Path | None = None) -> PluginRegistry:
    """Return a process-wide registry, lazily loaded from ``root``.

    Subsequent calls ignore ``root`` (the first call wins) so the CLI's
    ``parse_tag``/``generate_valid_tags`` see a stable view.
    """
    global _DEFAULT
    if _DEFAULT is None:
        if root is None:
            # This file lives at <repo>/sanity_gravity/plugins/registry.py;
            # walk three parents up to reach <repo>, then descend into plugins/.
            root = Path(__file__).resolve().parent.parent.parent / "plugins"
        _DEFAULT = PluginRegistry.from_dir(root)
    return _DEFAULT


def reset_default_registry() -> None:
    """Test helper: forget the cached default so the next call rescans.

    Also drops any plugin ``hooks.py`` modules from :data:`sys.modules`
    and clears the module-level default EventBus so a follow-up scan
    re-executes each plugin's hooks afresh. Without this, test isolation
    breaks (a hook registered against the default bus by an earlier test
    keeps firing in the next test's scan).
    """
    global _DEFAULT
    for mod_name in list(_LOADED_HOOK_MODULES):
        sys.modules.pop(mod_name, None)
    _LOADED_HOOK_MODULES.clear()
    _DEFAULT = None
    # Clear the module-level default bus so old @on subscriptions don't
    # leak into the next registry scan. Imported lazily to avoid a cycle
    # at import time.
    from sanity_gravity.core.eventbus import reset_default_bus
    reset_default_bus()
