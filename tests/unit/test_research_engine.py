"""
Tests for the Research Engine (Task 2 & 5).

Verifies the full pipeline:

    query → planning → collection → validation → synthesis → persistence

plus targeted unit tests for each stage. No network or LLM is used — a fake
search provider supplies deterministic sources and the planner/synthesizer run
in their heuristic (no-LLM) fallback.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from src.infra.workspace.artifact_registry import ArtifactRegistry
from src.infra.workspace.storage_service import StorageService
from src.infra.workspace.workspace_manager import WorkspaceManager
from src.research.collector import InformationCollector
from src.research.models import Source
from src.research.orchestrator import ResearchOrchestrator
from src.research.planner import QueryPlanner
from src.research.reporter import ReportBuilder
from src.research.storage import ResearchStorage
from src.research.synthesizer import KnowledgeSynthesizer
from src.research.validator import SourceValidator


if TYPE_CHECKING:
    from pathlib import Path


class FakeSearch:
    """Deterministic structured search provider."""

    def __init__(self, results: list[dict[str, str]] | None = None) -> None:
        self._results = results

    async def search_results(self, query: str, max_results: int = 5) -> list[dict[str, str]]:
        if self._results is not None:
            return self._results
        return [
            {"title": "NASA exoplanets", "snippet": "A" * 120,
             "url": "https://nasa.gov/exo", "provider": "web"},
            {"title": "Some blog", "snippet": "B" * 120,
             "url": "https://blog.example.com/x", "provider": "duckduckgo"},
            # Duplicate of the first (tests dedup).
            {"title": "NASA exoplanets", "snippet": "A" * 120,
             "url": "https://nasa.gov/exo", "provider": "web"},
        ]


def _orchestrator(storage: StorageService, search: FakeSearch) -> ResearchOrchestrator:
    return ResearchOrchestrator(
        planner=QueryPlanner(None, max_subtopics=3),
        collector=InformationCollector(search, max_fetch_pages=0),
        validator=SourceValidator(),
        synthesizer=KnowledgeSynthesizer(None),
        storage=ResearchStorage(storage),
    )


@pytest.fixture
def storage(tmp_path: Path) -> StorageService:
    root = tmp_path / "AMASPACE"
    wm = WorkspaceManager(root)
    wm.ensure_layout()
    return StorageService(wm, ArtifactRegistry(root / ".index"))


# ---------------------------------------------------------------------------
# Stage units
# ---------------------------------------------------------------------------


class TestPlanner:
    async def test_heuristic_plan_has_subtopics_and_questions(self) -> None:
        plan = await QueryPlanner(None, max_subtopics=4).plan("black holes")
        assert 1 <= len(plan.subtopics) <= 4
        assert plan.all_questions()
        assert all("black holes" in q.text for q in plan.all_questions())


class TestValidator:
    def test_scoring_prefers_authoritative_domains(self) -> None:
        gov = Source("g", "https://x.gov/a", "s", "web", domain="x.gov")
        blog = Source("b", "https://b.com/a", "s", "web", domain="b.com")
        v = SourceValidator()
        assert v.score(gov) > v.score(blog)

    def test_deduplication_by_url(self) -> None:
        s1 = Source("t", "https://a.com/x", "alpha content", "web", domain="a.com")
        s2 = Source("t", "https://a.com/x/", "alpha content", "web", domain="a.com")
        out = SourceValidator().validate([s1, s2])
        assert len(out) == 1

    def test_citations_are_numbered(self) -> None:
        out = SourceValidator.citations(
            [Source("Title", "https://a.com", "s", "web", domain="a.com")]
        )
        assert out[0].startswith("[1] Title")


class TestReporter:
    def test_markdown_contains_all_sections(self) -> None:
        from src.research.models import ResearchReport

        report = ResearchReport(
            topic="X",
            executive_summary="summary",
            detailed_analysis="analysis",
            key_findings=["f1"],
            risks=["r1"],
            open_questions=["q1"],
            future_directions=["d1"],
            sources=[Source("T", "https://a.com", "s", "web", domain="a.com")],
        )
        md = ReportBuilder().build_markdown(report)
        for header in (
            "# Research Report: X", "Executive Summary", "Key Findings",
            "Detailed Analysis", "Risks", "Open Questions", "Future Directions",
            "## Sources",
        ):
            assert header in md


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------


class TestPipeline:
    async def test_end_to_end_persists_three_artifacts(self, storage: StorageService) -> None:
        progress: list[str] = []

        async def _p(msg: str) -> None:
            progress.append(msg)

        result = await _orchestrator(storage, FakeSearch()).run(
            "exoplanets", request_id="r1", session_id="s1", progress=_p
        )

        names = {a.absolute_path.name for a in result.artifacts}
        assert names == {"report.md", "sources.json", "research_manifest.json"}
        assert all(a.absolute_path.exists() for a in result.artifacts)
        assert progress  # progress was reported

    async def test_dedup_reflected_in_manifest(self, storage: StorageService) -> None:
        result = await _orchestrator(storage, FakeSearch()).run("exoplanets")
        # 3 raw (incl. 1 dup) * N questions, deduped down — count must be < raw.
        assert result.manifest.source_count >= 1
        manifest_path = result.artifacts[0].absolute_path.parent / "research_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        assert manifest["source_count"] == result.manifest.source_count
        assert manifest["topic"] == "exoplanets"

    async def test_sources_json_is_valid_and_traceable(self, storage: StorageService) -> None:
        result = await _orchestrator(storage, FakeSearch()).run("exoplanets")
        sources_path = result.artifacts[0].absolute_path.parent / "sources.json"
        data = json.loads(sources_path.read_text())
        assert data["topic"] == "exoplanets"
        assert len(data["sources"]) == data["count"]
        assert all("url" in s and "reliability" in s for s in data["sources"])

    async def test_report_indexed_in_amaspace(self, storage: StorageService) -> None:
        await _orchestrator(storage, FakeSearch()).run("exoplanets")
        records = storage.registry.all()
        assert len(records) == 3
        assert any(r.relative_path.endswith("report.md") for r in records)

    async def test_empty_topic_rejected(self, storage: StorageService) -> None:
        with pytest.raises(ValueError):
            await _orchestrator(storage, FakeSearch()).run("   ")

    async def test_no_sources_still_produces_report(self, storage: StorageService) -> None:
        result = await _orchestrator(storage, FakeSearch(results=[])).run("obscure topic")
        assert result.manifest.source_count == 0
        assert result.primary_artifact is not None
        assert result.primary_artifact.absolute_path.exists()
