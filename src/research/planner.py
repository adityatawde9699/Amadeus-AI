"""
QueryPlanner — stage 1 of the research pipeline.

Decomposes a topic into subtopics, concrete research questions, and a list of
likely knowledge gaps. Uses the LLM when one is available and falls back to a
deterministic template so research never hard-fails on a no-LLM host.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable

from src.research.models import ResearchPlan, ResearchQuestion, SubTopic


logger = logging.getLogger(__name__)

LLMGenerate = Callable[..., Awaitable[str]]

_PLAN_PROMPT = """\
You are a research planner. Decompose the topic into a structured research plan.
Topic: "{topic}"

Return ONLY a JSON object with this exact shape (no prose, no markdown fence):
{{
  "subtopics": [
    {{"title": "<subtopic>", "questions": ["<question>", "<question>"]}}
  ],
  "knowledge_gaps": ["<gap>", "<gap>"]
}}
Produce at most {max_subtopics} subtopics, each with 2-3 focused, answerable
research questions. Keep questions specific and searchable.
"""


class QueryPlanner:
    def __init__(
        self,
        llm_generate: LLMGenerate | None = None,
        *,
        max_subtopics: int = 5,
    ) -> None:
        self._llm = llm_generate
        self._max_subtopics = max_subtopics

    async def plan(self, topic: str) -> ResearchPlan:
        topic = topic.strip()
        if self._llm is not None:
            plan = await self._plan_with_llm(topic)
            if plan and plan.subtopics:
                return plan
            logger.info("research_planner: LLM plan empty — using heuristic fallback")
        return self._heuristic_plan(topic)

    # ------------------------------------------------------------------
    async def _plan_with_llm(self, topic: str) -> ResearchPlan | None:
        prompt = _PLAN_PROMPT.format(topic=topic, max_subtopics=self._max_subtopics)
        try:
            raw = await self._llm(prompt, complexity="high", structured=True)  # type: ignore[misc]
        except TypeError:
            # Closures that don't accept kwargs.
            raw = await self._llm(prompt)  # type: ignore[misc]
        except Exception as exc:
            logger.warning("research_planner: LLM call failed: %s", exc)
            return None

        data = _extract_json(raw)
        if not isinstance(data, dict):
            return None

        subtopics: list[SubTopic] = []
        for st in data.get("subtopics", [])[: self._max_subtopics]:
            if not isinstance(st, dict):
                continue
            title = str(st.get("title", "")).strip()
            if not title:
                continue
            questions = [
                ResearchQuestion(text=str(q).strip(), subtopic=title)
                for q in st.get("questions", [])
                if str(q).strip()
            ]
            if questions:
                subtopics.append(SubTopic(title=title, questions=questions))

        gaps = [str(g).strip() for g in data.get("knowledge_gaps", []) if str(g).strip()]
        if not subtopics:
            return None
        return ResearchPlan(topic=topic, subtopics=subtopics, knowledge_gaps=gaps)

    # ------------------------------------------------------------------
    def _heuristic_plan(self, topic: str) -> ResearchPlan:
        """Deterministic fallback plan covering the canonical research facets."""
        facets = [
            ("Overview & Definitions", [
                f"What is {topic} and how is it defined?",
                f"What is the background and history of {topic}?",
            ]),
            ("Current State & Key Developments", [
                f"What is the current state of {topic}?",
                f"What are the most important recent developments in {topic}?",
            ]),
            ("Applications & Impact", [
                f"What are the main applications or use cases of {topic}?",
                f"What impact does {topic} have on its field or society?",
            ]),
            ("Challenges & Risks", [
                f"What are the main challenges, limitations, or risks of {topic}?",
            ]),
            ("Future Directions", [
                f"What is the future outlook for {topic}?",
            ]),
        ][: self._max_subtopics]

        subtopics = [
            SubTopic(
                title=title,
                questions=[ResearchQuestion(text=q, subtopic=title) for q in qs],
            )
            for title, qs in facets
        ]
        gaps = [f"Quantitative / empirical data on {topic} may require deeper sources."]
        return ResearchPlan(topic=topic, subtopics=subtopics, knowledge_gaps=gaps)


def _extract_json(raw: str) -> object:
    """Best-effort JSON extraction from a model response."""
    if not raw:
        return None
    text = raw.strip()
    # Strip ```json fences if present.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).rstrip("`").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None
