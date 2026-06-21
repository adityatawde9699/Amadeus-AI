"""
KnowledgeSynthesizer — stage 4 of the research pipeline.

Fuses the validated evidence into a structured :class:`ResearchReport`
(executive summary, detailed analysis, key findings, risks, open questions,
future directions). LLM-driven with a deterministic heuristic fallback so a
report is always produced — even offline or when the model misbehaves.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from src.research.models import ResearchPlan, ResearchReport, Source
from src.research.planner import _extract_json


logger = logging.getLogger(__name__)

LLMGenerate = Callable[..., Awaitable[str]]

_MAX_EVIDENCE_SOURCES = 12
_SNIPPET_CHARS = 350

_SYNTH_PROMPT = """\
You are a senior research analyst. Using ONLY the evidence below, synthesise a
rigorous, evidence-based report on the topic. Do not invent facts. Where the
evidence is thin, say so rather than speculating.

Topic: "{topic}"

Evidence (numbered sources):
{evidence}

Return ONLY a JSON object with this exact shape (no prose, no markdown fence):
{{
  "executive_summary": "<2-4 sentence summary>",
  "detailed_analysis": "<several paragraphs of analysis citing sources as [n]>",
  "key_findings": ["<finding>", "..."],
  "risks": ["<risk>", "..."],
  "open_questions": ["<question>", "..."],
  "future_directions": ["<direction>", "..."]
}}
"""


class KnowledgeSynthesizer:
    def __init__(self, llm_generate: LLMGenerate | None = None) -> None:
        self._llm = llm_generate

    async def synthesize(
        self,
        topic: str,
        plan: ResearchPlan,
        sources: list[Source],
    ) -> ResearchReport:
        if self._llm is not None and sources:
            report = await self._synthesize_with_llm(topic, plan, sources)
            if report and report.executive_summary:
                report.plan = plan
                report.sources = sources
                return report
            logger.info("research_synth: LLM synthesis empty — using heuristic fallback")
        return self._heuristic_report(topic, plan, sources)

    # ------------------------------------------------------------------
    async def _synthesize_with_llm(
        self, topic: str, plan: ResearchPlan, sources: list[Source]
    ) -> ResearchReport | None:
        evidence = self._format_evidence(sources)
        prompt = _SYNTH_PROMPT.format(topic=topic, evidence=evidence)
        try:
            raw = await self._llm(prompt, complexity="high", structured=True)  # type: ignore[misc]
        except TypeError:
            raw = await self._llm(prompt)  # type: ignore[misc]
        except Exception as exc:
            logger.warning("research_synth: LLM call failed: %s", exc)
            return None

        data = _extract_json(raw)
        if not isinstance(data, dict):
            return None

        return ResearchReport(
            topic=topic,
            executive_summary=str(data.get("executive_summary", "")).strip(),
            detailed_analysis=str(data.get("detailed_analysis", "")).strip(),
            key_findings=_str_list(data.get("key_findings")),
            risks=_str_list(data.get("risks")),
            open_questions=_str_list(data.get("open_questions")) or list(plan.knowledge_gaps),
            future_directions=_str_list(data.get("future_directions")),
        )

    # ------------------------------------------------------------------
    def _format_evidence(self, sources: list[Source]) -> str:
        lines = []
        for i, s in enumerate(sources[:_MAX_EVIDENCE_SOURCES], 1):
            snippet = s.snippet[:_SNIPPET_CHARS].replace("\n", " ")
            lines.append(f"[{i}] ({s.domain or s.provider}) {s.title}: {snippet}")
        return "\n".join(lines) if lines else "(no evidence gathered)"

    def _heuristic_report(
        self, topic: str, plan: ResearchPlan, sources: list[Source]
    ) -> ResearchReport:
        top = sources[:_MAX_EVIDENCE_SOURCES]
        if top:
            summary = (
                f"This report synthesises {len(sources)} source(s) on '{topic}'. "
                f"The most reliable evidence comes from "
                f"{', '.join(sorted({s.domain for s in top if s.domain})[:3]) or 'web sources'}."
            )
            analysis_parts = [
                f"- {s.title} ({s.domain or s.provider}): {s.snippet[:_SNIPPET_CHARS]}"
                for s in top
            ]
            analysis = (
                "Automated synthesis was unavailable, so the following are the "
                "highest-reliability findings gathered per source:\n\n"
                + "\n".join(analysis_parts)
            )
            findings = [f"{s.title} — {s.domain or s.provider}" for s in top[:5]]
        else:
            summary = (
                f"No usable sources were gathered for '{topic}'. The research "
                "could not be completed; try a more specific topic or check "
                "network access."
            )
            analysis = ""
            findings = []

        return ResearchReport(
            topic=topic,
            executive_summary=summary,
            detailed_analysis=analysis,
            key_findings=findings,
            risks=["Findings are unverified snippet-level extracts; treat as preliminary."],
            open_questions=list(plan.knowledge_gaps)
            or [f"Deeper, source-verified analysis of {topic} is still needed."],
            future_directions=[
                "Re-run with an LLM enabled for full synthesis.",
                "Add arXiv / Semantic Scholar collectors for academic depth.",
            ],
            plan=plan,
            sources=sources,
        )


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]
