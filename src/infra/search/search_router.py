"""
Tiered Search Router for Amadeus AI.

Routes search queries across free/paid providers in priority order:
1. Wikipedia API     — factual/encyclopedic queries (free, unlimited)
2. DuckDuckGo IA     — general instant answers (free, no key)
3. Brave Search      — general web (free: 2,000 req/month)
4. Tavily            — deep research (1,000 req/month free, paid after)

All HTTP calls use aiohttp for async, non-blocking I/O.
"""

import logging
from datetime import date

import aiohttp


logger = logging.getLogger(__name__)


class SearchRouter:
    """
    Routes search queries to the best available free or paid provider.

    Tracks Brave daily usage (2,000/month ≈ 66/day) to stay within free tier.
    Tavily is only used for depth="deep" queries when explicitly needed.
    """

    BRAVE_MONTHLY_LIMIT: int = 2000
    BRAVE_DAILY_LIMIT: int = 60  # REDUCED from 66 for safety margin

    _FACTUAL_PATTERNS: tuple[str, ...] = (
        "who is", "who was", "what is", "what are", "define",
        "explain", "history of", "biography", "when was", "where is",
    )

    def __init__(
        self,
        brave_api_key: str | None = None,
        tavily_api_key: str | None = None,
    ) -> None:
        self._brave_key = brave_api_key
        self._tavily_key = tavily_api_key
        self._brave_daily_count: int = 0
        self._count_date: date = date.today()
        self._force_free_search: bool = False

    def _reset_if_new_day(self) -> None:
        today = date.today()
        if today != self._count_date:
            self._brave_daily_count = 0
            self._count_date = today
            self._force_free_search = False

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

        if self._brave_daily_count >= 50:
            logger.warning(
                f"Brave search quota approaching limit: {self._brave_daily_count}/{self.BRAVE_DAILY_LIMIT}"
            )

        if self._brave_daily_count >= self.BRAVE_DAILY_LIMIT:
            self._force_free_search = True

        # Tier 1: Wikipedia for factual/encyclopedic queries
        if self._is_factual(query):
            result = await self._wikipedia_search(query)
            if result and len(result) > 80:
                logger.debug("Search: Wikipedia hit for '%s...'", query[:30])
                return result

        # Tier 2: DuckDuckGo Instant Answer (free, no key)
        ddg_result = await self._ddg_search(query)
        if ddg_result and len(ddg_result) > 100:
            logger.debug("Search: DuckDuckGo hit for '%s...'", query[:30])
            return ddg_result

        # Tier 3: Brave Search (free: 2,000/month ≈ 66/day)
        if self._brave_key and not self._force_free_search and self._brave_daily_count < self.BRAVE_DAILY_LIMIT:
            result = await self._brave_search(query)
            if result:
                self._brave_daily_count += 1
                logger.debug(
                    "Search: Brave hit (daily: %d/%d)",
                    self._brave_daily_count, self.BRAVE_DAILY_LIMIT,
                )
                return result

        # Tier 4: Tavily for deep research (use sparingly)
        if self._tavily_key and depth == "deep":
            result = await self._tavily_search(query)
            if result:
                logger.debug("Search: Tavily deep hit for '%s...'", query[:30])
                return result

        # Fallback: return DuckDuckGo result even if short
        return ddg_result or "Search results unavailable at this time."

    async def _wikipedia_search(self, query: str) -> str:
        """Query Wikipedia REST API for a summary."""
        try:
            url = "https://en.wikipedia.org/api/rest_v1/page/summary/"
            # Extract the main subject from the query for the Wikipedia title
            subject = query.replace("who is ", "").replace("what is ", "").replace("define ", "").strip()
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(url + subject.replace(" ", "_")) as r:
                    if r.status == 200:
                        data = await r.json()
                        extract = data.get("extract", "")
                        return extract[:800] if extract else ""
            return ""
        except Exception as e:
            logger.debug("Wikipedia search failed: %s", type(e).__name__)
            return ""

    async def _ddg_search(self, query: str) -> str:
        """Query DuckDuckGo Instant Answer API — no key required."""
        try:
            url = "https://api.duckduckgo.com/"
            params: dict[str, str] = {"q": query, "format": "json", "no_redirect": "1", "no_html": "1"}
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(url, params=params) as r:
                    if r.status == 200:
                        data = await r.json(content_type=None)
                        # Prefer AbstractText, then Answer
                        return (
                            data.get("AbstractText")
                            or data.get("Answer")
                            or ""
                        )
            return ""
        except Exception as e:
            logger.debug("DuckDuckGo search failed: %s", type(e).__name__)
            return ""

    async def _brave_search(self, query: str) -> str:
        """Query Brave Search API (2,000 req/month free)."""
        try:
            url = "https://api.search.brave.com/res/v1/web/search"
            headers = {
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": self._brave_key or "",
            }
            params: dict[str, str] = {"q": query, "count": "5"}
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
                async with session.get(url, headers=headers, params=params) as r:
                    if r.status == 200:
                        data = await r.json()
                        results = data.get("web", {}).get("results", [])
                        snippets = []
                        for result in results[:3]:
                            title = result.get("title", "")
                            desc = result.get("description", "")
                            if desc:
                                snippets.append(f"{title}: {desc}")
                        return "\n".join(snippets)
            return ""
        except Exception as e:
            logger.debug("Brave search failed: %s", type(e).__name__)
            return ""

    async def _tavily_search(self, query: str) -> str:
        """Query Tavily API for deep research (1,000 req/month free)."""
        try:
            url = "https://api.tavily.com/search"
            payload = {
                "api_key": self._tavily_key,
                "query": query,
                "search_depth": "advanced",
                "max_results": 3,
            }
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.post(url, json=payload) as r:
                    if r.status == 200:
                        data = await r.json()
                        results = data.get("results", [])
                        snippets = []
                        for result in results[:3]:
                            content = result.get("content", "")
                            if content:
                                snippets.append(content[:300])
                        return "\n\n".join(snippets)
            return ""
        except Exception as e:
            logger.debug("Tavily search failed: %s", type(e).__name__)
            return ""

    def get_usage_report(self) -> dict:
        """Return current search provider usage stats."""
        return {
            "date": self._count_date.isoformat(),
            "brave_daily_count": self._brave_daily_count,
            "brave_daily_limit": self.BRAVE_DAILY_LIMIT,
            "brave_configured": self._brave_key is not None,
            "tavily_configured": self._tavily_key is not None,
        }
