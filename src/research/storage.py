"""
ResearchStorage — stage 6 of the research pipeline.

Persists a research run into ``AMASPACE/research/<date>_<slug>/`` as the three
canonical artifacts. It is a thin adapter over the shared
:class:`StorageService`, so research output is traceable, indexed, and
contained exactly like every other artifact in AMASPACE.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.core.domain.artifacts import Artifact, ArtifactRef, ArtifactType
from src.infra.workspace.workspace_manager import slugify
from src.research.reporter import ReportBuilder


if TYPE_CHECKING:
    from src.infra.workspace.storage_service import StorageService
    from src.research.models import ResearchManifest, ResearchReport


class ResearchStorage:
    def __init__(self, storage_service: StorageService) -> None:
        self._storage = storage_service
        self._reporter = ReportBuilder()

    def make_slug(self, topic: str, date_str: str) -> str:
        return f"{date_str}_{slugify(topic, default='research')}"

    def persist(
        self,
        report: ResearchReport,
        manifest: ResearchManifest,
        *,
        request_id: str | None = None,
        session_id: str | None = None,
    ) -> list[ArtifactRef]:
        """Write report.md, sources.json, research_manifest.json into one run dir."""
        subdir = manifest.slug
        common = {
            "origin": "research_engine",
            "subdir": subdir,
            "request_id": request_id,
            "session_id": session_id,
            "tags": ("research", slugify(report.topic, default="topic")),
        }

        refs: list[ArtifactRef] = []

        # report.md first — primary artifact (front-matter on).
        refs.append(
            self._storage.persist(
                Artifact(
                    artifact_type=ArtifactType.RESEARCH,
                    title=f"Research Report: {report.topic}",
                    content=self._reporter.build_markdown(report),
                    filename="report.md",
                    content_type="text/markdown",
                    front_matter=True,
                    **common,  # type: ignore[arg-type]
                )
            )
        )

        # sources.json + research_manifest.json — structured, no front-matter.
        refs.append(
            self._storage.persist(
                Artifact(
                    artifact_type=ArtifactType.RESEARCH,
                    title=f"Sources: {report.topic}",
                    content=self._reporter.build_sources_json(report),
                    filename="sources.json",
                    content_type="application/json",
                    front_matter=False,
                    **common,  # type: ignore[arg-type]
                )
            )
        )
        refs.append(
            self._storage.persist(
                Artifact(
                    artifact_type=ArtifactType.RESEARCH,
                    title=f"Manifest: {report.topic}",
                    content=self._reporter.build_manifest_json(manifest),
                    filename="research_manifest.json",
                    content_type="application/json",
                    front_matter=False,
                    **common,  # type: ignore[arg-type]
                )
            )
        )
        return refs
