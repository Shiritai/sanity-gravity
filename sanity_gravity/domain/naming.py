"""Naming: the single source of every name derived from a sandbox identity.

Construction is canonicalization: a ``Naming`` is built from a ``Tag``,
and a ``Tag`` can only exist in canonical form (its constructor enforces
the slug alphabet). There is therefore no "normalize before use" step
anywhere downstream - the type system already did it.

Every method below owns exactly one f-string, and that f-string appears
nowhere else in the repository. A guard test keeps it that way.

``project`` is optional because most names depend on the tag alone; the
project-scoped ones (``container``, ``volume_external``,
``backup_image``) raise :class:`NamingError` when it is absent rather
than silently emitting a name with an empty segment.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from sanity_gravity.domain.errors import SanityError
from sanity_gravity.domain.layers import LayerKind, LayerRef
from sanity_gravity.domain.tags import Tag


class NamingError(SanityError, ValueError):
    """A name was requested without the identity parts it derives from."""


@dataclass(frozen=True)
class Naming:
    """All tag-derived names, each from exactly one method."""

    tag: Tag
    project: str | None = None

    IMAGE_REPO: ClassVar[str] = "sanity-gravity"
    VOLUME_PREFIX: ClassVar[str] = "sg"
    CONFIG_DIR: ClassVar[str] = "config"
    BACKUP_REPO: ClassVar[str] = "sanity-migrate"

    def _require_project(self) -> str:
        if self.project is None:
            raise NamingError(
                f"a project-scoped name was requested for {self.tag} "
                "but this Naming carries no project"
            )
        return self.project

    # -- names that depend on the tag alone ---------------------------

    def image(self) -> str:
        """Local image ref: what ``docker build -t`` writes, ``pull``
        re-tags to, and compose falls back to without an override."""
        return f"{self.IMAGE_REPO}:{self.tag}"

    def service(self) -> str:
        """Compose service name. Identical to the tag by design: the
        service key written into the YAML and the name ``docker compose
        up -d <service>`` receives must agree; stating the law once
        makes it checkable."""
        return str(self.tag)

    def env_var(self) -> str:
        """Image-override env var. Load-bearing across a module
        boundary: hooks/up SETS it for ``--image`` and the generated
        compose file READS it - two copies of this transform would let
        ``--image`` fail silently; one copy cannot."""
        return f"SANITY_IMAGE_{str(self.tag).upper().replace('-', '_')}"

    def image_expr(self) -> str:
        """The compose ``image:`` value: override var, image fallback.
        Owns the interpolation shape so no caller concatenates
        ``env_var()`` and ``image()`` by hand."""
        return f"${{{self.env_var()}:-{self.image()}}}"

    def volume(self) -> str:
        """Compose-local volume KEY (underscore form) - distinct from
        the external docker volume name, see ``volume_external``. Both
        grammars live here, adjacent, so the difference stays visible."""
        return f"{self.VOLUME_PREFIX}_{self.tag}"

    def compose_file(self) -> str:
        """Per-tag compose overlay path. A repo-relative POSIX path by
        definition (docker compose -f consumes it), so it is spelled as
        a plain f-string like every other name here - which also keeps
        domain/ free of os, as the import contract requires."""
        return f"{self.CONFIG_DIR}/docker-compose.{self.tag}.yml"

    def ghcr(self, repo: str, ver: str) -> str:
        """Remote image ref. ``repo`` is the lowercase owner/name
        prefix; ``ver`` the version tag (v0.3.0 / sha-abc1234 /
        latest). The publish side lives in .github/workflows; a guard
        test compares the two rather than trusting them to agree."""
        return f"ghcr.io/{repo}-{self.tag}:{ver}"

    # -- names that also depend on the project ------------------------

    def container(self) -> str:
        """Container name; the ``-1`` is compose's replica ordinal."""
        return f"{self._require_project()}-{self.service()}-1"

    def volume_external(self, project_expr: str | None = None) -> str:
        """External docker volume name. ``project_expr`` lets the
        compose generator pass the literal interpolation
        ``${COMPOSE_PROJECT_NAME:-...}`` the YAML needs."""
        project = project_expr if project_expr is not None else self._require_project()
        return f"{self.VOLUME_PREFIX}-{project}-{self.tag}"

    def backup_image(self, timestamp: str) -> str:
        """Rollback snapshot ref: the anchor of the upgrade rollback
        contract, previously hand-rolled in verbs/upgrade."""
        return f"{self.BACKUP_REPO}/{self._require_project()}-{self.tag}:{timestamp}"

    # -- layer names: the second grammar ------------------------------

    @staticmethod
    def layer(kind: LayerKind, detail: str | None = None) -> str:
        """Render a layer name. The SOLE owner of the layer grammar;
        inverse of ``parse_layer`` (a property test binds the pair).

        Static rather than instance-bound: intermediate layers (_base,
        _base-xfce) carry no full tag, and the connector layer's detail
        IS the tag string."""
        if kind is LayerKind.BASE:
            return "_base"
        if detail is None:
            raise NamingError(f"{kind} layer name requires a detail")
        if kind is LayerKind.DESKTOP:
            return f"_base-{detail}"
        if kind is LayerKind.AGENT:
            return f"_{detail}"
        return detail  # CONNECTOR: the final image is the tag

    @classmethod
    def parse_layer(cls, name: str) -> LayerRef:
        """Decode a layer name. The SOLE owner of layer parsing.

        Injectivity holds by construction, not by rule order: slugs
        contain no '-', and 'base' is a reserved slug
        (tags.RESERVED_SLUGS), so '_base-x' can only be a desktop
        layer and a prefix-free name can only be a final tag."""
        if not name.startswith("_"):
            return LayerRef.of_tag(Tag.parse(name))
        body = name[1:]
        if body == "base":
            return LayerRef.base()
        if body.startswith("base-"):
            return LayerRef.of(LayerKind.DESKTOP, body[len("base-"):])
        return LayerRef.of(LayerKind.AGENT, body)

    @staticmethod
    def layer_image(ref: LayerRef) -> str:
        """Full docker ref for a layer: repository prefix + layer name.
        A combinator over ``image()``'s prefix and ``layer()``'s name,
        so the planner writes zero f-strings of its own."""
        return f"{Naming.IMAGE_REPO}:{Naming.layer(ref.kind, ref.detail)}"
