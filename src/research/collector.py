"""
InformationCollector — stage 2 of the research pipeline.

Gathers raw sources for every research question using the tiered
:class:`SearchRouter` (Wikipedia → DuckDuckGo → Tavily). Optionally enriches
the top sources by fetching and extracting the full page text so the
synthesizer has more than a one-line snippet to work from.

Source *scoring* and *deduplication* are intentionally NOT done here — that is
the validator's responsibility, keeping collection a pure gathering stage.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol
from urllib.parse import urlparse

import httpx

from src.research.models import ResearchPlan, Source


logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str], Awaitable[None]]


class SearchProvider(Protocol):
    """The slice of SearchRouter the collector depends on (eases testing)."""

    async def search_results(self, query: str, max_results: int = 5) -> list[dict[str, str]]: ...


class InformationCollector:
    def __init__(
        self,
        search_provider: SearchProvider,
        *,
        max_sources_per_question: int = 5,
        fetch_timeout: int = 15,
        max_fetch_pages: int = 8,
    ) -> None:
        self._search = search_provider
        self._max_sources = max_sources_per_question
        self._fetch_timeout = fetch_timeout
        self._max_fetch_pages = max_fetch_pages

    async def collect(
        self,
        plan: ResearchPlan,
        progress: ProgressCallback | None = None,
    ) -> list[Source]:
        """Gather sources for every question in the plan."""
        # Initialise the provider's HTTP session if it exposes one.
        init = getattr(self._search, "initialize", None)
        if callable(init):
            try:
                await init()
            except Exception:  # pragma: no cover - best-effort
                logger.debug("search provider initialize() failed", exc_info=True)

        questions = plan.all_questions()
        collected: list[Source] = []

        for idx, question in enumerate(questions, 1):
            if progress and idx % 2 == 1:
                await progress(f"Gathering sources ({idx}/{len(questions)})")
            try:
                raw = await self._search.search_results(
                    question.text, max_results=self._max_sources
                )
            except Exception as exc:
                logger.warning("collector: search failed for %r: %s", question.text, exc)
                continue

            for item in raw:
                collected.append(
                    Source(
                        title=item.get("title", "").strip() or item.get("url", ""),
                        url=item.get("url", "").strip(),
                        snippet=item.get("snippet", "").strip(),
                        provider=item.get("provider", "web"),
                        domain=_domain_of(item.get("url", "")),
                        question=question.text,
                    )
                )

        await self._enrich_top_sources(collected, progress)
        return collected

    # ------------------------------------------------------------------
    async def _enrich_top_sources(
        self,
        sources: list[Source],
        progress: ProgressCallback | None,
    ) -> None:
        """Fetch full page text for a bounded number of the richest sources."""
        if self._max_fetch_pages <= 0:
            return

        # Prefer http(s) sources with the shortest snippets (most to gain).
        fetchable = [
            s for s in sources if s.url.startswith(("http://", "https://"))
        ]
        fetchable.sort(key=lambda s: len(s.snippet))
        targets = fetchable[: self._max_fetch_pages]
        if not targets:
            return

        if progress:
            await progress(f"Reading {len(targets)} source page(s)")

        async with httpx.AsyncClient(
            timeout=self._fetch_timeout,
            follow_redirects=True,
            headers={"User-Agent": "AmadeusAI/5.0 ResearchBot"},
        ) as client:
            await asyncio.gather(
                *(self._fetch_into(client, s) for s in targets),
                return_exceptions=True,
            )

    async def _fetch_into(self, client: httpx.AsyncClient, source: Source) -> None:
        try:
            resp = await client.get(source.url)
            resp.raise_for_status()
            if "text/html" not in resp.headers.get("content-type", ""):
                return
            text = _html_to_text(resp.text)
            if len(text) > len(source.snippet):
                source.snippet = text[:2000]
        except Exception as exc:  # pragma: no cover - network variance
            logger.debug("collector: fetch failed for %s: %s", source.url, type(exc).__name__)


def _domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def _html_to_text(html: str) -> str:
    """Reuse the project's HTML→text extractor for consistency."""
    from src.infra.tools.web_research_tools import _html_to_text as _impl

    return _impl(html)
