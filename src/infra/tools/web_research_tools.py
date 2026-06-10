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

from src.infra.tools.base import Tool, ToolCategory, tool


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


def build_web_research_tools(search_router: Any = None) -> list[Tool]:
    """Build web research tools for the LLM tool registry.

    Args:
        search_router: Optional SearchRouter instance. If None, will be lazily
                       imported from the global container on first use.
    """

    @tool(
        name="web_search",
        description=(
            "Search the web for current information, news, sports scores, people, places, or any factual query. "
            "Use this tool for: 'who won', 'latest news', 'current score', 'what happened', 'tell me about', "
            "'look up', 'search for', 'find out', 'today's weather', 'recent events'. "
            "Always use this instead of saying 'I'll search' — just search."
        ),
        category=ToolCategory.WEB_RESEARCH,
        parameters={
            "query": {"type": "string", "description": "The search query to look up"},
        },
    )
    async def web_search(query: str, **kwargs: Any) -> str:
        """Search the web for current information, news, scores, or facts."""
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

    @tool(
        name="fetch_webpage_content",
        description=(
            "Fetches a specific webpage by URL and extracts clean, readable text (strips HTML). "
            "Returns up to 4000 chars of content. Use when user provides a specific URL. "
            "Trigger: 'read this webpage', 'get content from URL', 'extract text from'."
        ),
        category=ToolCategory.WEB_RESEARCH,
        parameters={
            "url": {"type": "string", "description": "The URL to fetch and parse"},
        },
    )
    async def fetch_webpage_content(url: str, **kwargs: Any) -> str:
        """Fetch a webpage and extract its text content."""
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
        web_search._tool_metadata,  # type: ignore[attr-defined]
        fetch_webpage_content._tool_metadata,  # type: ignore[attr-defined]
    ]
