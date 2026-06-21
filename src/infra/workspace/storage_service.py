"""
StorageService — the high-level persistence facade for AMASPACE.

Hand it an :class:`Artifact` and it does everything required to make that
output traceable and reusable:

  1. Resolve a collision-safe, contained path (``WorkspaceManager``).
  2. Prepend a YAML front-matter block (for text/markdown artifacts).
  3. Write the file.
  4. Write a sidecar ``<file>.meta.json`` with full traceability metadata.
  5. Append the metadata to the append-only index (``ArtifactRegistry``).
  6. Return an :class:`ArtifactRef` (path + identity, no body) for notifications.

This is the one place all output handlers funnel through, which is what makes
"every artifact lands in the right AMASPACE location" automatic for future
tools rather than something each tool re-implements.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from src.core.domain.artifacts import (
    Artifact,
    ArtifactMetadata,
    ArtifactRef,
    ArtifactType,
)
from src.infra.workspace.artifact_registry import ArtifactRegistry
from src.infra.workspace.workspace_manager import WorkspaceManager


logger = logging.getLogger(__name__)

# Content types that get a YAML front-matter header when front_matter=True.
_TEXTUAL_TYPES = ("text/markdown", "text/plain", "text/x-markdown")


class StorageService:
    """Persists artifacts into AMASPACE with metadata + indexing."""

    def __init__(
        self,
        workspace: WorkspaceManager,
        registry: ArtifactRegistry,
    ) -> None:
        self._workspace = workspace
        self._registry = registry

    @property
    def workspace(self) -> WorkspaceManager:
        return self._workspace

    @property
    def registry(self) -> ArtifactRegistry:
        return self._registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def persist(self, artifact: Artifact) -> ArtifactRef:
        """Write *artifact* to AMASPACE and return a pointer to it."""
        self._workspace.ensure_layout()

        date_str = artifact.created_at.strftime("%Y-%m-%d")
        # When a research run (or similar) supplies an explicit filename we keep
        # it verbatim (e.g. report.md) and skip the date prefix; otherwise we
        # derive a dated name from the title.
        path = self._workspace.resolve(
            artifact.artifact_type,
            filename=artifact.filename,
            title=artifact.title,
            subdir=artifact.subdir,
            timestamp_prefix=artifact.filename is None,
            date_str=date_str,
        )

        body = self._compose_body(artifact)
        path.write_text(body, encoding="utf-8")
        size = path.stat().st_size

        metadata = ArtifactMetadata(
            artifact_id=artifact.artifact_id,
            artifact_type=artifact.artifact_type,
            title=artifact.title,
            created_at=artifact.created_at,
            origin=artifact.origin,
            relative_path=self._workspace.relative_path(path),
            request_id=artifact.request_id,
            session_id=artifact.session_id,
            content_type=artifact.content_type,
            size_bytes=size,
            tags=artifact.tags,
            extra=artifact.extra,
        )

        self._write_sidecar(path, metadata)
        self._registry.append(metadata)

        logger.info(
            "artifact_persisted type=%s path=%s bytes=%d",
            artifact.artifact_type.value,
            metadata.relative_path,
            size,
        )

        return ArtifactRef(
            artifact_id=metadata.artifact_id,
            artifact_type=metadata.artifact_type,
            title=metadata.title,
            absolute_path=path,
            relative_path=metadata.relative_path,
            size_bytes=size,
        )

    def persist_text(
        self,
        *,
        artifact_type: ArtifactType,
        title: str,
        content: str,
        origin: str,
        **kwargs: object,
    ) -> ArtifactRef:
        """Convenience wrapper for the common text-artifact case."""
        artifact = Artifact(
            artifact_type=artifact_type,
            title=title,
            content=content,
            origin=origin,
            **kwargs,  # type: ignore[arg-type]
        )
        return self.persist(artifact)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _compose_body(self, artifact: Artifact) -> str:
        if not artifact.front_matter or artifact.content_type not in _TEXTUAL_TYPES:
            return artifact.content

        fm_lines = [
            "---",
            f"id: {artifact.artifact_id}",
            f"created: {artifact.created_at.isoformat()}",
            f"type: {artifact.artifact_type.value}",
            f"title: {artifact.title}",
            f"origin: {artifact.origin}",
        ]
        if artifact.request_id:
            fm_lines.append(f"request_id: {artifact.request_id}")
        if artifact.session_id:
            fm_lines.append(f"session_id: {artifact.session_id}")
        tags = ", ".join(artifact.tags)
        fm_lines.append(f"tags: [{tags}]")
        fm_lines.append("---")
        fm_lines.append("")
        return "\n".join(fm_lines) + artifact.content

    def _write_sidecar(self, path: Path, metadata: ArtifactMetadata) -> None:
        sidecar = path.with_suffix(path.suffix + ".meta.json")
        try:
            sidecar.write_text(
                json.dumps(metadata.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("artifact_sidecar_write_failed path=%s: %s", sidecar, exc)
