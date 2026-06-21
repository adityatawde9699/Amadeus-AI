"""
Amadeus Research Engine.

A production-grade, modular deep-research pipeline:

    planner       — decompose a topic into subtopics + research questions
    collector     — gather sources across web / encyclopedic / deep providers
    validator     — reliability scoring, deduplication, citations, conflicts
    synthesizer   — LLM knowledge synthesis (summary, findings, risks, ...)
    reporter      — render report.md / sources.json / research_manifest.json
    storage       — persist the run into AMASPACE/research/<slug>/
    orchestrator  — coordinate the whole pipeline end-to-end

Every stage is independently testable and swappable, leaving room for future
additions (arXiv, Semantic Scholar, local document ingestion, vector indexing,
multi-agent research) without touching the orchestration contract.
"""

from __future__ import annotations

from src.research.models import (
    ResearchManifest,
    ResearchPlan,
    ResearchQuestion,
    ResearchReport,
    ResearchResult,
    Source,
    SubTopic,
)
from src.research.orchestrator import ResearchOrchestrator


__all__ = [
    "ResearchManifest",
    "ResearchOrchestrator",
    "ResearchPlan",
    "ResearchQuestion",
    "ResearchReport",
    "ResearchResult",
    "Source",
    "SubTopic",
]
