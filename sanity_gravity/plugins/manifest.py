"""Plugin manifest loader.

Each plugin under ``plugins/<kind>/<slug>/`` ships a ``manifest.toml``
describing the plugin's identity, capabilities, build artifact, and any
optional ports / compose overlay / environment / announce template.

The schema is **symmetric across kinds**: agent, desktop, and connector
manifests may all declare any of the optional sections below. Historically
only connectors did, but plugins of any kind sometimes need extra env
vars (e.g. an agent that wants ``OPENAI_API_KEY``), extra ports, or a
custom announce blurb. Generators / hooks merge contributions from all
three plugins of a tag (agent + desktop + connector) — see
``_compose_gen.generate_compose_for_tag`` and ``up_hooks.announce`` for
the merge semantics (last-write-wins on collisions; connector first,
then agent, then desktop).

Schema (TOML)::

    [plugin]                                            # required
    slug = "kasm"; name = "KasmVNC"; kind = "connector"; api_version = "1"
    tier = "official"        # optional: official | community | deprecated

    [capabilities]                                      # optional
    provides = ["http-gui"]
    requires = ["display"]

    [build]                                             # required
    dockerfile = "Dockerfile"

    # optional, any kind
    [ports.<label>]
    internal = 8444
    default  = 8444
    env_var  = "KASM_PORT"

    # optional, any kind
    [compose]
    shm_size = "512m"; restart = "unless-stopped"; stop_grace_period = "30s"

    # optional, any kind — env vars merged into the service `environment`
    [environment]
    VNC_PW = "${VNC_PW:-${HOST_PASSWORD}}"
    OPENAI_API_KEY = "${OPENAI_API_KEY:-}"

    # optional, any kind — str.format template with placeholders:
    #   {ports.<label>}, {user}, {password}, {tag}, {connector}, {container_name}
    # Each non-empty plugin's template is rendered separately and the
    # resulting AccessInfo fields concatenated into a single block.
    [announce]
    template = "..."

    # optional, agents providing the "ide" capability - the container-
    # side maintenance contract consumed by the ``ide`` verb.
    [ide]
    command = ["/usr/local/bin/gravity-cli", "ide"]
    inject  = ["usr/local/bin/gravity-cli"]

The loader is intentionally tiny: validate fields, fail fast with line-
ish diagnostics, and return frozen dataclasses. No defaults are inferred
from outside the manifest itself, so every plugin is self-describing.

If a plugin needs to express something the schema can't (a runtime
side effect, a state-machine step), drop a ``hooks.py`` next to
``manifest.toml`` — see :mod:`sanity_gravity.plugins.registry` for how
those modules are loaded into the EventBus.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - 3.11+ is the project minimum
    import tomli as tomllib  # type: ignore[import-not-found]


__all__ = [
    "ManifestError",
    "PortSpec",
    "ComposeOverlay",
    "AnnounceSpec",
    "IdeSpec",
    "PluginManifest",
    "TIERS",
    "load_manifest",
]


_VALID_KINDS = {"base-image", "agent", "desktop", "connector"}

# Support tiers, ordered least to most restrictive. A tag's tier is the
# most restrictive tier among its three plugins. Only ``official``
# plugins enter the CI build/verify and release publish matrix;
# ``community`` and ``deprecated`` stay locally buildable but leave the
# matrix, and ``deprecated`` additionally warns on build/up.
TIERS: tuple[str, ...] = ("official", "community", "deprecated")

# Manifest schema versions this loader understands. Update when bumping
# the schema with a backwards-incompatible change; an unknown version is
# rejected at load time so old plugins do not silently mis-parse against
# new code.
#
# The check is **literal-string equality** — ``"1.0"`` and ``"v1"`` are
# rejected. The error message names the accepted form so authors know how
# to fix their manifest.
SUPPORTED_API_VERSIONS: frozenset[str] = frozenset({"1"})


class ManifestError(ValueError):
    """Raised on schema or value violations in a plugin manifest."""


@dataclass(frozen=True)
class PortSpec:
    """A single named port on a plugin (any kind may declare ports).

    ``legacy_slug`` (optional) names the key under
    ``UpContext.resolved_ports`` where the orchestrator stashes the
    runtime-resolved port. Connectors set this so the announce hook can
    look up the resolved value without a kernel-side hardcoded table.

    The four legacy slugs in use today are ``"ssh"`` / ``"kasm"`` /
    ``"vnc"`` / ``"novnc"`` (matching the CLI's static ``--*-port``
    flags). ``auto_port_alloc`` allocates every manifest-declared slug
    and ``resolve_ephemeral`` probes ``internal`` on the tag's own
    manifests, so a new connector introducing a new slug needs no
    kernel changes.

    When ``legacy_slug`` is unset the port label itself is used, so a
    manifest that picks ``label`` matching the runtime slug works
    without the field.
    """

    label: str
    internal: int
    default: int
    env_var: str
    legacy_slug: str | None = None


@dataclass(frozen=True)
class ComposeOverlay:
    """Optional compose-service overrides (any kind may declare these)."""

    shm_size: str | None = None
    restart: str | None = None
    stop_grace_period: str | None = None

    def is_empty(self) -> bool:
        return (
            self.shm_size is None
            and self.restart is None
            and self.stop_grace_period is None
        )


@dataclass(frozen=True)
class AnnounceSpec:
    """Optional announce template (str.format) — any kind may declare it."""

    template: str


@dataclass(frozen=True)
class IdeSpec:
    """Optional container-side IDE maintenance contract.

    Declared by agents that provide the ``ide`` capability. ``command``
    is the in-container argv prefix the ``ide`` verb invokes (the ide
    subcommand is appended to it). ``inject`` lists rootfs-relative
    files the verb refreshes (``docker cp``) into the running container
    beforehand, so stale sandboxes get the current host checkout's
    tooling; each entry maps to ``/<path>`` in-container because
    ``rootfs/`` mirrors the container filesystem root.
    """

    command: tuple[str, ...]
    inject: tuple[str, ...] = ()


@dataclass(frozen=True)
class PluginManifest:
    """Parsed manifest backed by a single ``manifest.toml`` file."""

    slug: str
    name: str
    kind: str
    api_version: str
    provides: tuple[str, ...]
    requires: tuple[str, ...]
    dockerfile: str
    tier: str = "official"
    ports: tuple[PortSpec, ...] = ()
    compose: ComposeOverlay = field(default_factory=ComposeOverlay)
    environment: tuple[tuple[str, str], ...] = ()
    announce: AnnounceSpec | None = None
    ide: IdeSpec | None = None
    source_path: Path | None = None

    @property
    def dir(self) -> Path:
        """Directory containing this manifest (Docker build context).

        Raises :class:`ManifestError` if ``source_path`` was not set
        (typically only happens for manifests synthesized in tests; a
        manifest produced by :func:`load_manifest` always carries the
        path of the file it came from).
        """
        if self.source_path is None:
            raise ManifestError(
                f"Manifest {self.slug!r} has no source_path; "
                f"path-derived attributes (dir, dockerfile_path) are unavailable"
            )
        return self.source_path.parent

    @property
    def dockerfile_path(self) -> Path:
        """Absolute path to the plugin's Dockerfile.

        Same precondition as :attr:`dir` — raises :class:`ManifestError`
        if ``source_path`` is unset rather than yielding a misleading
        relative path.
        """
        if self.source_path is None:
            raise ManifestError(
                f"Manifest {self.slug!r} has no source_path; "
                f"dockerfile_path is unavailable"
            )
        return self.dir / self.dockerfile

    def ports_by_label(self) -> dict[str, PortSpec]:
        return {p.label: p for p in self.ports}


def _require(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise ManifestError(f"{where}: missing required key '{key}'")
    return d[key]


def _str(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise ManifestError(f"{where}: expected string, got {type(value).__name__}")
    return value


def _str_list(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ManifestError(f"{where}: expected list, got {type(value).__name__}")
    out: list[str] = []
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise ManifestError(
                f"{where}[{i}]: expected string, got {type(item).__name__}"
            )
        out.append(item)
    return tuple(out)


def _int(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestError(f"{where}: expected int, got {type(value).__name__}")
    return value


def _parse_ports(table: dict[str, Any] | None, where: str) -> tuple[PortSpec, ...]:
    if not table:
        return ()
    if not isinstance(table, dict):
        raise ManifestError(f"{where}: expected table")
    out: list[PortSpec] = []
    for label, sub in table.items():
        sub_where = f"{where}.{label}"
        if not isinstance(sub, dict):
            raise ManifestError(f"{sub_where}: expected table")
        legacy_slug = None
        if "legacy_slug" in sub:
            legacy_slug = _str(sub["legacy_slug"], f"{sub_where}.legacy_slug")
        out.append(
            PortSpec(
                label=label,
                internal=_int(_require(sub, "internal", sub_where), f"{sub_where}.internal"),
                default=_int(_require(sub, "default", sub_where), f"{sub_where}.default"),
                env_var=_str(_require(sub, "env_var", sub_where), f"{sub_where}.env_var"),
                legacy_slug=legacy_slug,
            )
        )
    return tuple(out)


def _parse_compose(table: dict[str, Any] | None, where: str) -> ComposeOverlay:
    if not table:
        return ComposeOverlay()
    return ComposeOverlay(
        shm_size=_str(table["shm_size"], f"{where}.shm_size") if "shm_size" in table else None,
        restart=_str(table["restart"], f"{where}.restart") if "restart" in table else None,
        stop_grace_period=(
            _str(table["stop_grace_period"], f"{where}.stop_grace_period")
            if "stop_grace_period" in table
            else None
        ),
    )


def _parse_environment(
    table: dict[str, Any] | None, where: str
) -> tuple[tuple[str, str], ...]:
    if not table:
        return ()
    out: list[tuple[str, str]] = []
    for k, v in table.items():
        out.append((str(k), _str(v, f"{where}.{k}")))
    return tuple(out)


def _parse_announce(table: dict[str, Any] | None, where: str) -> AnnounceSpec | None:
    if not table:
        return None
    template = _str(_require(table, "template", where), f"{where}.template")
    return AnnounceSpec(template=template)


def _parse_ide(table: dict[str, Any] | None, where: str) -> IdeSpec | None:
    if not table:
        return None
    command = _str_list(_require(table, "command", where), f"{where}.command")
    if not command:
        raise ManifestError(f"{where}.command: must not be empty")
    inject = _str_list(table.get("inject", []), f"{where}.inject")
    for i, rel in enumerate(inject):
        # Absolute or traversing entries would resolve outside the
        # plugin's rootfs/ tree; fail closed at load time.
        if rel.startswith("/") or ".." in rel.split("/"):
            raise ManifestError(
                f"{where}.inject[{i}]: '{rel}' must be a rootfs-relative path"
            )
    return IdeSpec(command=command, inject=inject)


def load_manifest(path: str | Path) -> PluginManifest:
    """Load + validate a single ``manifest.toml`` file.

    Raises :class:`ManifestError` on schema violations.
    """
    p = Path(path)
    if not p.is_file():
        raise ManifestError(f"manifest not found: {p}")
    try:
        with p.open("rb") as fp:
            data = tomllib.load(fp)
    except tomllib.TOMLDecodeError as exc:  # type: ignore[attr-defined]
        raise ManifestError(f"{p}: TOML parse error: {exc}") from exc

    plugin = _require(data, "plugin", str(p))
    if not isinstance(plugin, dict):
        raise ManifestError(f"{p}: [plugin] must be a table")

    slug = _str(_require(plugin, "slug", f"{p}:[plugin]"), f"{p}:[plugin].slug")
    name = _str(_require(plugin, "name", f"{p}:[plugin]"), f"{p}:[plugin].name")
    kind = _str(_require(plugin, "kind", f"{p}:[plugin]"), f"{p}:[plugin].kind")
    api_version = _str(
        _require(plugin, "api_version", f"{p}:[plugin]"),
        f"{p}:[plugin].api_version",
    )

    if kind not in _VALID_KINDS:
        raise ManifestError(
            f"{p}: [plugin].kind must be one of {sorted(_VALID_KINDS)}, got '{kind}'"
        )

    tier = "official"
    if "tier" in plugin:
        tier = _str(plugin["tier"], f"{p}:[plugin].tier")
        if tier not in TIERS:
            raise ManifestError(
                f"{p}: [plugin].tier must be one of {list(TIERS)}, got '{tier}'"
            )

    if api_version not in SUPPORTED_API_VERSIONS:
        accepted = sorted(SUPPORTED_API_VERSIONS)
        hint = ""
        # ``1.0`` / ``v1`` look like "the same thing" to humans but are
        # not equal strings. Surface a targeted hint so the author can
        # fix the manifest in one edit.
        normalized = api_version.lstrip("vV").rstrip()
        if normalized.endswith(".0"):
            normalized = normalized[:-2]
        if normalized in SUPPORTED_API_VERSIONS:
            hint = (
                f" (the comparison is exact-string; try "
                f'api_version = "{normalized}" instead of "{api_version}")'
            )
        raise ManifestError(
            f"{p}: [plugin].api_version '{api_version}' is not supported; "
            f"this loader accepts exactly one of {accepted}.{hint}"
        )

    capabilities = data.get("capabilities") or {}
    provides = _str_list(
        capabilities.get("provides", []), f"{p}:[capabilities].provides"
    )
    requires = _str_list(
        capabilities.get("requires", []), f"{p}:[capabilities].requires"
    )

    build = _require(data, "build", str(p))
    if not isinstance(build, dict):
        raise ManifestError(f"{p}: [build] must be a table")
    dockerfile = _str(
        _require(build, "dockerfile", f"{p}:[build]"), f"{p}:[build].dockerfile"
    )

    # Optional sections — the schema is symmetric: any kind (agent /
    # desktop / connector) may declare ports, compose overlay,
    # environment, or an announce template. Generators merge
    # contributions across all three plugins of a tag.
    ports = _parse_ports(data.get("ports"), f"{p}:[ports]")
    compose = _parse_compose(data.get("compose"), f"{p}:[compose]")
    environment = _parse_environment(data.get("environment"), f"{p}:[environment]")
    announce = _parse_announce(data.get("announce"), f"{p}:[announce]")
    ide = _parse_ide(data.get("ide"), f"{p}:[ide]")

    return PluginManifest(
        slug=slug,
        name=name,
        kind=kind,
        api_version=api_version,
        tier=tier,
        provides=provides,
        requires=requires,
        dockerfile=dockerfile,
        ports=ports,
        compose=compose,
        environment=environment,
        announce=announce,
        ide=ide,
        source_path=p,
    )
