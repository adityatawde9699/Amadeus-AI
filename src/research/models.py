"""
Domain models for the Research Engine.

Pure dataclasses — no I/O, no LLM, no network. They define the contract that
flows between the planner, collector, validator, synthesizer, reporter, and
storage stages, which keeps each stage independently testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from src.core.domain.artifacts import ArtifactRef


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResearchQuestion:
    """A single, answerable research question under a subtopic."""

    text: str
    subtopic: str


@dataclass
class SubTopic:
    """A facet of the overall topic with its own research questions."""

    title: str
    questions: list[ResearchQuestion] = field(default_factory=list)


@dataclass
class ResearchPlan:
    """The decomposition of a topic into subtopics, questions, and gaps."""

    topic: str
    subtopics: list[SubTopic] = field(default_factory=list)
    knowledge_gaps: list[str] = field(default_factory=list)

    def all_questions(self) -> list[ResearchQuestion]:
        return [q for st in self.subtopics for q in st.questions]


# ---------------------------------------------------------------------------
# Collection / evidence
# ---------------------------------------------------------------------------


@dataclass
class Source:
    """A single retrieved source with provenance and an assigned reliability."""

    title: str
    url: str
    snippet: str
    provider: str
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    reliability: float = 0.0  # 0.0 (unknown) .. 1.0 (authoritative)
    domain: str = ""
    # The research question this source was gathered for (best-effort).
    question: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "provider": self.provider,
            "domain": self.domain,
            "reliability": round(self.reliability, 3),
            "question": self.question,
            "retrieved_at": self.retrieved_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Synthesis / report
# ---------------------------------------------------------------------------


@dataclass
class ResearchReport:
    """The synthesised knowledge product for a topic."""

    topic: str
    executive_summary: str = ""
    detailed_analysis: str = ""
    key_findings: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    future_directions: list[str] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    plan: ResearchPlan | None = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ResearchManifest:
    """Machine-readable record of how a research run was produced."""

    topic: str
    slug: str
    created_at: datetime
    subtopic_count: int
    question_count: int
    source_count: int
    providers: list[str]
    stage_durations_ms: dict[str, float]
    conflicts: list[str] = field(default_factory=list)
    request_id: str | None = None
    session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "slug": self.slug,
            "created_at": self.created_at.isoformat(),
            "subtopic_count": self.subtopic_count,
            "question_count": self.question_count,
            "source_count": self.source_count,
            "providers": self.providers,
            "stage_durations_ms": {k: round(v, 1) for k, v in self.stage_durations_ms.items()},
            "conflicts": self.conflicts,
            "request_id": self.request_id,
            "session_id": self.session_id,
        }


@dataclass
class ResearchResult:
    """The orchestrator's return value: report + manifest + saved artifacts."""

    report: ResearchReport
    manifest: ResearchManifest
    artifacts: list[ArtifactRef] = field(default_factory=list)

    @property
    def primary_artifact(self) -> ArtifactRef | None:
        """The report.md artifact, if present (first by convention)."""
        return self.artifacts[0] if self.artifacts else None
