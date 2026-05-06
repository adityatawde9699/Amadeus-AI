"""
Web Research Tools for Amadeus AI.

Provides an LLM-callable tool for fetching and parsing web page
content into clean text suitable for LLM consumption.
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


def build_web_research_tools() -> list[dict[str, Any]]:
    """Build web research tools for the LLM tool registry."""

    async def fetch_webpage_content(url: str) -> str:
        """
        Fetch a webpage and extract its text content.

        Strips HTML tags, scripts, and styles. Returns clean text
        suitable for LLM analysis (capped at 4000 chars).
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
            "name": "fetch_webpage_content",
            "description": "Fetches a webpage by URL and extracts clean, readable text (strips HTML, scripts, styles). Returns up to 4000 chars of content. Use this when you need to read a specific webpage. Trigger: 'read this webpage', 'get content from URL', 'scrape this page', 'extract text from'",
            "function": fetch_webpage_content,
            "parameters": {
                "url": {"type": "string", "description": "The URL to fetch and parse"},
            },
        },
    ]
