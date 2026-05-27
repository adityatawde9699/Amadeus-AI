"""
Web Research Tools for Amadeus AI.

Provides two LLM-callable tools:
  1. web_search(query)         — searches the web via SearchRouter (DDG → Tavily → Wikipedia)
  2. fetch_webpage_content(url) — fetches and parses a specific URL
"""

import logging
from typing import Any

import httpx
from bs4 import BeautifulSoup


logger = logging.getLogger(__name__)

MAX_PAGE_CHARS = 4000  # Max characters to return from a page


def _html_to_text(html: str) -> str:
    """Convert HTML to clean readable text."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove non-content elements
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "meta", "link"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)

    # Collapse blank lines
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    clean = "\n".join(lines)
    return clean[:MAX_PAGE_CHARS]


def build_web_research_tools(search_router: Any = None) -> list[dict[str, Any]]:
    """Build web research tools for the LLM tool registry.

    Args:
        search_router: Optional SearchRouter instance. If None, will be lazily
                       imported from the global container on first use.
    """

    async def web_search(query: str) -> str:
        """
        Search the web for current information, news, scores, or facts.

        Uses DuckDuckGo (free) first, then Tavily for deeper research.
        Returns a formatted summary of the top results with sources.

        Use this tool whenever the user asks about:
        - Current events, news, sports scores, stock prices
        - People, places, companies, products
        - Any factual question that may require up-to-date information
        - "Who won", "What happened", "Latest", "Current", "Today's"

        Trigger phrases: 'search for', 'look up', 'find out', 'who won',
        'latest news', 'current score', 'what happened', 'tell me about'.
        """
        if not query or not query.strip():
            return "❌ Please provide a search query."

        try:
            # Prefer injected router, fall back to global container
            router = search_router
            if router is None:
                from src.container import get_search_router
                router = get_search_router()
                # Ensure the HTTP session is initialized
                if hasattr(router, "initialize"):
                    await router.initialize()

            result = await router.search(query.strip())
            if result and result != "Search results unavailable at this time.":
                return result
            return f"🔍 No results found for: {query}"
        except Exception as exc:
            logger.exception("web_search tool failed: %s", exc)
            return f"❌ Search failed: {exc}"

    async def fetch_webpage_content(url: str) -> str:
        """
        Fetch a webpage and extract its text content.

        Strips HTML tags, scripts, and styles. Returns clean text
        suitable for LLM analysis (capped at 4000 chars).

        Use this when the user gives you a specific URL to read.
        Trigger: 'read this webpage', 'get content from URL', 'scrape this page'.
        """
        if not url.startswith(("http://", "https://")):
            return "❌ Invalid URL — must start with http:// or https://"

        try:
            async with httpx.AsyncClient(
                timeout=15,
                follow_redirects=True,
                headers={"User-Agent": "AmadeusAI/2.0 WebResearchBot"},
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return f"⚠️ Unsupported content type: {content_type}"

            text = _html_to_text(resp.text)
            if not text:
                return "⚠️ Page was empty or contained no readable text."

            return f"🌐 **Content from** `{url}`:\n\n{text}"

        except httpx.HTTPStatusError as exc:
            return f"❌ HTTP error {exc.response.status_code} fetching {url}"
        except httpx.TimeoutException:
            return f"⏱️ Timeout fetching {url} (15s limit)"
        except Exception as exc:
            logger.exception("web_research_fetch_failed")
            return f"❌ Error: {exc}"

    return [
        {
            "name": "web_search",
            "description": (
                "Search the web for current information, news, sports scores, people, places, or any factual query. "
                "Use this tool for: 'who won', 'latest news', 'current score', 'what happened', 'tell me about', "
                "'look up', 'search for', 'find out', 'today's weather', 'recent events'. "
                "Always use this instead of saying 'I'll search' — just search."
            ),
            "function": web_search,
            "parameters": {
                "query": {"type": "string", "description": "The search query to look up"},
            },
        },
        {
            "name": "fetch_webpage_content",
            "description": (
                "Fetches a specific webpage by URL and extracts clean, readable text (strips HTML). "
                "Returns up to 4000 chars of content. Use when user provides a specific URL. "
                "Trigger: 'read this webpage', 'get content from URL', 'extract text from'."
            ),
            "function": fetch_webpage_content,
            "parameters": {
                "url": {"type": "string", "description": "The URL to fetch and parse"},
            },
        },
    ]
