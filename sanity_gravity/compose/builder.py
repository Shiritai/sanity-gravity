"""Typed Compose model + builder.

ComposeBuilder replaces the three string-template ``generate_*_compose``
helpers in ``sanity-cli`` with a small, testable, type-safe surface.

Usage::

    svc = ComposeService(
        name="ag-xfce-kasm",
        image="${SANITY_IMAGE_AG_XFCE_KASM:-sanity-gravity:ag-xfce-kasm}",
        command=["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"],
        environment={"HOST_USER": "${HOST_USER:-developer}"},
        ports=["${SSH_HOST_PORT:-2222}:22"],
        shm_size="512m",
    )
    yaml_text = (
        ComposeBuilder()
        .add_service(svc)
        .merge_environment(svc.name, {"HOST_UID": "${HOST_UID:-1000}"})
        .render()
    )

Design notes
------------
- ``environment`` is rendered as a list (``KEY=VALUE`` strings) rather than
  a mapping, matching the legacy template and Compose's preferred form
  for shell-expanded values like ``${HOST_USER:-developer}``.
- ``${VAR:-default}`` strings round-trip verbatim through ``yaml.safe_dump``
  because they are plain strings to YAML.
- Numeric-looking values (``1.5``, ``"512m"``) are emitted via ``str``;
  PyYAML auto-quotes ones that would otherwise re-parse as numbers
  (e.g. ``'1.5'``), keeping docker-compose happy.
- Output uses block style (``default_flow_style=False``) and preserves
  the insertion order we hand to it (``sort_keys=False``).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import yaml  # PyYAML — required by sanity-cli compose generation


__all__ = ["ComposeService", "ComposeBuilder"]


@dataclass
class ComposeService:
    """A single docker-compose service in declarative form.

    Field order mirrors the legacy template's emit order so the rendered
    YAML reads top-to-bottom the same way: image, command, environment,
    volumes, ports, network_mode, shm_size, restart, stop_grace_period,
    ulimits, labels, deploy.
    """

    name: str
    image: str
    command: list[str] | None = None
    environment: dict[str, str] = field(default_factory=dict)
    volumes: list[str] = field(default_factory=list)
    ports: list[str] = field(default_factory=list)
    network_mode: str | None = None
    shm_size: str | None = None
    restart: str | None = None
    stop_grace_period: str | None = None
    cap_drop: list[str] | None = None
    cap_add: list[str] | None = None
    pids_limit: int | None = None
    ulimits: dict[str, dict[str, int]] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    deploy: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Render this service as a dict suitable for ``yaml.safe_dump``.

        Empty/None fields are omitted so an overlay service (e.g. one that
        only contributes volumes) doesn't carry through ``image: null``.
        """
        out: dict[str, Any] = {}
        if self.image:
            out["image"] = self.image
        if self.command is not None:
            out["command"] = list(self.command)
        if self.environment:
            # List form (KEY=VALUE) — preserves shell expansion for entries
            # like HOST_USER=${HOST_USER:-developer}.
            out["environment"] = [f"{k}={v}" for k, v in self.environment.items()]
        if self.volumes:
            out["volumes"] = list(self.volumes)
        if self.ports:
            out["ports"] = list(self.ports)
        if self.network_mode:
            out["network_mode"] = self.network_mode
        if self.shm_size:
            out["shm_size"] = self.shm_size
        if self.restart:
            out["restart"] = self.restart
        if self.stop_grace_period:
            out["stop_grace_period"] = self.stop_grace_period
        if self.cap_drop is not None:
            out["cap_drop"] = list(self.cap_drop)
        if self.cap_add is not None:
            out["cap_add"] = list(self.cap_add)
        if self.pids_limit is not None:
            out["pids_limit"] = self.pids_limit
        if self.ulimits:
            out["ulimits"] = {k: dict(v) for k, v in self.ulimits.items()}
        if self.labels:
            out["labels"] = dict(self.labels)
        if self.deploy:
            out["deploy"] = _deepcopy_dict(self.deploy)
        return out


class ComposeBuilder:
    """Accumulates services and merges overlays, then renders to YAML."""

    __slots__ = ("services", "volumes")

    def __init__(self) -> None:
        self.services: dict[str, ComposeService] = {}
        # Top-level named volumes. Maps volume name -> config dict (or
        # None for a default-configured volume, which YAML renders as a
        # bare ``<name>:`` line — what docker-compose wants for a simple
        # per-project named volume).
        self.volumes: dict[str, dict[str, Any] | None] = {}

    # -- service management ------------------------------------------

    def add_service(self, svc: ComposeService) -> "ComposeBuilder":
        """Register a service. Replaces any existing entry of the same name."""
        self.services[svc.name] = svc
        return self

    def patch(self, name: str, **kw: Any) -> "ComposeBuilder":
        """Partial update of an existing service.

        Equivalent to ``setattr`` for each kw on the registered service.
        Raises ``KeyError`` if the service does not exist (callers must
        ``add_service`` first).
        """
        svc = self.services[name]
        for k, v in kw.items():
            if not hasattr(svc, k):
                raise AttributeError(f"ComposeService has no field {k!r}")
            setattr(svc, k, v)
        return self

    def declare_volume(
        self,
        name: str,
        config: dict[str, Any] | None = None,
    ) -> "ComposeBuilder":
        """Declare a top-level named volume.

        ``config=None`` (the default) emits a bare ``<name>:`` entry —
        a docker-managed volume with default settings, which is what a
        simple per-project persistent volume needs. Re-declaring the
        same name is idempotent (last config wins).
        """
        self.volumes[name] = config
        return self

    # -- additive merges ---------------------------------------------

    def merge_environment(self, name: str, env: dict[str, str]) -> "ComposeBuilder":
        """Update the service's environment dict (later values win)."""
        svc = self.services[name]
        svc.environment.update(env)
        return self

    def merge_volumes(self, name: str, volumes: list[str]) -> "ComposeBuilder":
        """Append volumes to the service, skipping exact duplicates.

        Idempotent: re-applying the same overlay does not multiply mounts.
        """
        svc = self.services[name]
        for v in volumes:
            if v not in svc.volumes:
                svc.volumes.append(v)
        return self

    def merge_ports(self, name: str, ports: list[str]) -> "ComposeBuilder":
        """Append ports to the service, skipping exact duplicates."""
        svc = self.services[name]
        for p in ports:
            if p not in svc.ports:
                svc.ports.append(p)
        return self

    def merge_labels(self, name: str, labels: dict[str, str]) -> "ComposeBuilder":
        """Merge labels into the service (later values win)."""
        svc = self.services[name]
        svc.labels.update(labels)
        return self

    def set_deploy_resources(
        self,
        name: str,
        *,
        cpus: str | None = None,
        memory: str | None = None,
    ) -> "ComposeBuilder":
        """Set ``deploy.resources.limits`` on the service.

        Quotes values via ``str()``; YAML emits ``cpus: '1.5'`` so the
        compose parser sees a string (matching docker-compose conventions).
        """
        if cpus is None and memory is None:
            return self
        svc = self.services[name]
        deploy = dict(svc.deploy) if svc.deploy else {}
        resources = dict(deploy.get("resources") or {})
        limits = dict(resources.get("limits") or {})
        if cpus is not None:
            limits["cpus"] = str(cpus)
        if memory is not None:
            limits["memory"] = str(memory)
        resources["limits"] = limits
        deploy["resources"] = resources
        svc.deploy = deploy
        return self

    # -- rendering ---------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "services": {n: s.to_dict() for n, s in self.services.items()}
        }
        if self.volumes:
            # ``{name: None}`` round-trips through yaml.safe_dump as a
            # bare ``name:`` line — the canonical default-volume form.
            out["volumes"] = {
                n: (_deepcopy_dict(c) if c else None)
                for n, c in self.volumes.items()
            }
        return out

    def render(self) -> str:
        """Emit the compose document as a YAML string.

        - ``sort_keys=False`` preserves the order we constructed.
        - ``default_flow_style=False`` forces block style for readability
          and docker-compose compatibility.
        """
        return yaml.safe_dump(
            self.to_dict(),
            sort_keys=False,
            default_flow_style=False,
        )

    def write(self, path: str) -> str:
        """Render and write to ``path`` (creating parent dirs). Returns ``path``."""
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(self.render())
        return path


def _deepcopy_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Shallow-recursive copy for deploy-style nested dicts.

    We only need to defend against callers mutating the source after
    ``add_service``; the deploy block is small and JSON-shaped, so no
    need for ``copy.deepcopy``'s overhead.
    """
    out: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out[k] = _deepcopy_dict(v)
        elif isinstance(v, list):
            out[k] = list(v)
        else:
            out[k] = v
    return out
