"""
Tiered Search Router for Amadeus AI.

Routes search queries across free/paid providers in priority order:
1. Wikipedia API     — factual/encyclopedic queries (free, unlimited)
2. DuckDuckGo       — general web search via duckduckgo-search lib (free, no key)
3. Tavily            — deep research (1,000 req/month free, paid after)

All HTTP calls use aiohttp for async, non-blocking I/O.
"""

import asyncio
import logging
from datetime import date

import aiohttp


logger = logging.getLogger(__name__)


class SearchRouter:
    """
    Routes search queries to the best available free or paid provider.

    Tier 1: Wikipedia (factual/encyclopedic queries — free, unlimited)
    Tier 2: DuckDuckGo text search (general queries — free, no API key)
    Tier 3: Tavily (deep research — 1,000 req/month free, API key required)
    """

    _FACTUAL_PATTERNS: tuple[str, ...] = (
        "who is",
        "who was",
        "what is",
        "what are",
        "define",
        "explain",
        "history of",
        "biography",
        "when was",
        "where is",
    )

    def __init__(
        self,
        tavily_api_key: str | None = None,
    ) -> None:
        self._tavily_key = tavily_api_key
        self._count_date: date = date.today()
        self._session: aiohttp.ClientSession | None = None

    async def initialize(self) -> None:
        """Initialize shared HTTP session for search providers."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        """Close shared HTTP session."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            await self.initialize()
        if self._session is None:
            raise RuntimeError("search router HTTP session is unavailable")
        return self._session

    def _reset_if_new_day(self) -> None:
        today = date.today()
        if today != self._count_date:
            self._count_date = today

    def _is_factual(self, query: str) -> bool:
        """Check if query is encyclopedic (better served by Wikipedia)."""
        lower = query.lower()
        return any(p in lower for p in self._FACTUAL_PATTERNS)

    async def search(self, query: str, depth: str = "quick") -> str:
        """
        Search for information using the best available provider.

        Args:
            query: Search query string
            depth: "quick" (fast, free tier) or "deep" (Tavily, may cost)

        Returns:
            String with search result(s), or empty string if all fail
        """
        self._reset_if_new_day()

        # Tier 1: Wikipedia for factual/encyclopedic queries
        if self._is_factual(query):
            result = await self._wikipedia_search(query)
            if result and len(result) > 80:
                logger.debug("Search: Wikipedia hit for '%s...'", query[:30])
                return result

        # Tier 2: DuckDuckGo text search (free, no key required)
        ddg_result = await self._ddg_search(query)
        if ddg_result and len(ddg_result) > 60:
            logger.debug("Search: DuckDuckGo hit for '%s...'", query[:30])
            return ddg_result

        # Tier 3: Tavily for deep research OR as fallback when DDG fails
        if self._tavily_key:
            result = await self._tavily_search(query)
            if result:
                logger.debug("Search: Tavily hit for '%s...'", query[:30])
                return result

        # Fallback: return whatever DDG returned, even if short
        return ddg_result or "Search results unavailable at this time."

    async def _wikipedia_search(self, query: str) -> str:
        """Query Wikipedia REST API for a summary."""
        try:
            url = "https://en.wikipedia.org/api/rest_v1/page/summary/"
            session = await self._get_session()
            # Extract the main subject from the query for the Wikipedia title
            subject = (
                query.replace("who is ", "").replace("what is ", "").replace("define ", "").strip()
            )
            async with session.get(
                url + subject.replace(" ", "_"), timeout=aiohttp.ClientTimeout(total=5)
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    extract = data.get("extract", "")
                    return extract[:800] if extract else ""
            return ""
        except Exception as e:
            logger.debug("Wikipedia search failed: %s", type(e).__name__)
            return ""

    async def _ddg_search(self, query: str) -> str:
        """Search DuckDuckGo using the ddgs library.

        Returns a formatted string of the top 3-5 results with titles,
        snippets, and source URLs.
        """
        try:
            # Try the new package name first (renamed from duckduckgo_search → ddgs)
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS  # legacy name, still works

            # Run the synchronous DDGS in a thread to avoid blocking the event loop
            def _do_search() -> list[dict]:
                with DDGS() as ddgs:
                    return list(ddgs.text(query, max_results=5))

            results = await asyncio.to_thread(_do_search)

            if not results:
                return ""

            lines: list[str] = []
            for i, r in enumerate(results[:5], 1):
                title = r.get("title", "")
                body = r.get("body", "")
                href = r.get("href", "")
                if title and body:
                    lines.append(f"{i}. **{title}**\n   {body}\n   Source: {href}")

            if not lines:
                return ""

            return "🔍 Search results:\n\n" + "\n\n".join(lines)

        except ImportError:
            logger.warning(
                "Neither 'ddgs' nor 'duckduckgo-search' is installed. "
                "Install with: pip install ddgs"
            )
            return ""
        except Exception as e:
            logger.debug("DuckDuckGo search failed: %s — %s", type(e).__name__, e)
            return ""


    async def _tavily_search(self, query: str) -> str:
        """Query Tavily API for deep research (1,000 req/month free)."""
        try:
            url = "https://api.tavily.com/search"
            session = await self._get_session()
            payload = {
                "api_key": self._tavily_key,
                "query": query,
                "search_depth": "advanced",
                "max_results": 3,
            }
            async with session.post(
                url, json=payload, timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    results = data.get("results", [])
                    snippets = []
                    for result in results[:3]:
                        title = result.get("title", "")
                        content = result.get("content", "")
                        url_str = result.get("url", "")
                        if content:
                            snippet = f"**{title}**\n{content[:300]}"
                            if url_str:
                                snippet += f"\nSource: {url_str}"
                            snippets.append(snippet)
                    return "\n\n".join(snippets)
            return ""
        except Exception as e:
            logger.debug("Tavily search failed: %s", type(e).__name__)
            return ""

    def get_usage_report(self) -> dict:
        """Return current search provider usage stats."""
        return {
            "date": self._count_date.isoformat(),
            "tavily_configured": self._tavily_key is not None,
        }
