"""
Workspace Search Tool for Amadeus AI.

Exposes `search_workspace` as a registered Amadeus tool so that
any natural-language query like:
    "What port does Amadeus expose in docker-compose?"
    "Where did I define the Qdrant path?"
    "Show me the function that handles SVM routing"

...automatically triggers a semantic search across the indexed local filesystem
and injects the relevant file snippets into Amadeus's context.

Registration:
    This module follows the standard tool module pattern.
    Call get_workspace_tools() during tool registration in amadeus_service.py.
"""

from __future__ import annotations

import logging

from src.core.config import get_settings
from src.infra.tools.base import Tool, ToolCategory, tool



logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton indexer — loaded once, reused on every search call
# ---------------------------------------------------------------------------

_indexer = None


def _get_indexer():
    """Lazy-load and return the shared WorkspaceIndexer instance."""
    global _indexer
    if _indexer is None:
        try:
            from src.infra.workspace_indexer import WorkspaceIndexer

            settings = get_settings()
            index_dir = settings.BASE_DIR / "data" / "workspace_index"

            _indexer = WorkspaceIndexer(
                root=r"C:\Users\ASUS\Downloads",
                index_dir=index_dir,
                max_chunks=15_000,  # ~46 MB matrix + ~20 MB BM25 — safe on 4 GB RAM
            )


            # Try to load an existing index from disk.
            # If none exists, the tool will still work but return a helpful message.
            if not _indexer.load():
                logger.warning(
                    "workspace_search: No index found. "
                    "Run `python scripts/index_workspace.py` to build the index."
                )
        except Exception as exc:
            logger.error("workspace_search: failed to initialise indexer: %s", exc)
    return _indexer


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------


@tool(
    name="search_workspace",
    description=(
        "Semantically search all local files on this machine "
        "(Python, Markdown, config, YAML, TOML, .env, etc.) "
        "to answer questions about local projects, configs, or code. "
        "Trigger: 'what port does X expose', 'where is Y defined', "
        "'find the function that does Z', 'show me the config for', "
        "'search my files for', 'look in my projects for'. "
        "Returns verbatim snippets with file paths and line numbers."
    ),
    category=ToolCategory.INFORMATION,
    parameters={
        "query": {
            "type": "string",
            "description": "Natural language question or keyword to search for in local files",
        },
        "top_k": {
            "type": "integer",
            "description": "Number of results to return (default: 5, max: 10)",
            "required": False,
        },
    },
)
async def search_workspace(query: str, top_k: int = 5) -> str:
    """
    Search the local workspace index and return relevant file snippets.
    """
    if not query or not query.strip():
        return "Error: Please provide a search query."

    top_k = max(1, min(top_k, 10))

    indexer = _get_indexer()
    if indexer is None:
        return (
            "Workspace index is unavailable. "
            "Please run `python scripts/index_workspace.py` first to build the index."
        )

    if not indexer.is_ready:
        return (
            f"Workspace index not built yet ({indexer.chunk_count} chunks loaded). "
            "Run `python scripts/index_workspace.py` to build the index."
        )

    try:
        results = indexer.search(query.strip(), top_k=top_k)

        if not results:
            return (
                f"No relevant files found for: '{query}'. "
                "The index may not cover that content, or try a different query."
            )

        lines = [f"Found {len(results)} relevant file snippet(s) for: '{query}'\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"--- Result {i} ---")
            lines.append(r.format())
            lines.append("")

        return "\n".join(lines)

    except Exception as exc:
        logger.error("search_workspace: unexpected error: %s", exc)
        return f"Workspace search failed: {exc}"


# ---------------------------------------------------------------------------
# Tool collection
# ---------------------------------------------------------------------------


def get_workspace_tools() -> list[Tool]:
    """Return all workspace tools for manual registration."""
    tools = []
    for _name, obj in globals().items():
        if hasattr(obj, "_tool_metadata"):
            tools.append(obj._tool_metadata)
    return tools
