"""
ResearchOrchestrator — coordinates the full research pipeline.

    plan → collect → validate → synthesize → report → persist

It owns timing/telemetry and progress reporting, but delegates every unit of
real work to a single-responsibility stage. The result is a
:class:`ResearchResult` carrying the report, the manifest, and pointers to the
artifacts written under AMASPACE — never the raw bodies, so callers (e.g. the
Telegram transport) can notify without leaking content.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from src.research.collector import InformationCollector
from src.research.models import ResearchManifest, ResearchResult
from src.research.planner import QueryPlanner
from src.research.reporter import ReportBuilder
from src.research.storage import ResearchStorage
from src.research.synthesizer import KnowledgeSynthesizer
from src.research.validator import SourceValidator


logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str], Awaitable[None]]


class ResearchOrchestrator:
    def __init__(
        self,
        planner: QueryPlanner,
        collector: InformationCollector,
        validator: SourceValidator,
        synthesizer: KnowledgeSynthesizer,
        storage: ResearchStorage,
        reporter: ReportBuilder | None = None,
    ) -> None:
        self._planner = planner
        self._collector = collector
        self._validator = validator
        self._synthesizer = synthesizer
        self._storage = storage
        self._reporter = reporter or ReportBuilder()

    async def run(
        self,
        topic: str,
        *,
        request_id: str | None = None,
        session_id: str | None = None,
        progress: ProgressCallback | None = None,
    ) -> ResearchResult:
        topic = topic.strip()
        if not topic:
            raise ValueError("Research topic must not be empty")

        durations: dict[str, float] = {}
        started = datetime.now(UTC)

        async def _emit(msg: str) -> None:
            if progress:
                await progress(msg)

        # 1. Plan -------------------------------------------------------
        await _emit("Decomposing topic into research questions")
        with _StageTimer(durations, "planning"):
            plan = await self._planner.plan(topic)
        logger.info(
            "research: planned %d subtopic(s), %d question(s)",
            len(plan.subtopics), len(plan.all_questions()),
        )

        # 2. Collect ----------------------------------------------------
        await _emit("Gathering sources")
        with _StageTimer(durations, "collection"):
            raw_sources = await self._collector.collect(plan, progress)

        # 3. Validate ---------------------------------------------------
        await _emit("Scoring and de-duplicating sources")
        with _StageTimer(durations, "validation"):
            sources = self._validator.validate(raw_sources)
            conflicts = self._validator.detect_conflicts(sources)

        # 4. Synthesize -------------------------------------------------
        await _emit("Synthesising findings")
        with _StageTimer(durations, "synthesis"):
            report = await self._synthesizer.synthesize(topic, plan, sources)
        report.generated_at = started

        # 5/6. Report + persist ----------------------------------------
        await _emit("Writing report")
        slug = self._storage.make_slug(topic, started.strftime("%Y-%m-%d"))
        manifest = ResearchManifest(
            topic=topic,
            slug=slug,
            created_at=started,
            subtopic_count=len(plan.subtopics),
            question_count=len(plan.all_questions()),
            source_count=len(sources),
            providers=sorted({s.provider for s in sources}),
            stage_durations_ms=durations,
            conflicts=conflicts,
            request_id=request_id,
            session_id=session_id,
        )
        with _StageTimer(durations, "persistence"):
            artifacts = self._storage.persist(
                report, manifest, request_id=request_id, session_id=session_id
            )

        logger.info(
            "research_complete topic=%r sources=%d artifacts=%d",
            topic, len(sources), len(artifacts),
        )
        return ResearchResult(report=report, manifest=manifest, artifacts=artifacts)


class _StageTimer:
    """Tiny context manager that records elapsed ms into a dict."""

    def __init__(self, sink: dict[str, float], key: str) -> None:
        self._sink = sink
        self._key = key
        self._start = 0.0

    def __enter__(self) -> _StageTimer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        self._sink[self._key] = (time.perf_counter() - self._start) * 1000.0
