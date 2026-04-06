"""
Sandboxed Filesystem Tools for Amadeus AI.

All file operations are strictly confined to the agent workspace
directory (DATA_DIR/agent_workspace). Directory traversal is blocked.
"""

import logging
from pathlib import Path

from src.core.config import get_settings
from src.infra.tools.base import Tool, ToolCategory, tool


logger = logging.getLogger(__name__)


def _get_workspace() -> Path:
    """Get the sandboxed workspace directory, creating it if needed."""
    settings = get_settings()
    return settings.AGENT_WORKSPACE


def _safe_resolve(user_path: str) -> Path | None:
    """
    Resolve a user-provided path within the sandbox.

    Returns None if the resolved path escapes the workspace.
    """
    workspace = _get_workspace()
    try:
        target = (workspace / user_path).resolve()
        # Security: ensure the resolved path is still inside the workspace
        if not str(target).startswith(str(workspace.resolve())):
            logger.warning("sandbox_escape_blocked", extra={"attempted": user_path})
            return None
        return target
    except (ValueError, OSError):
        return None


@tool(
    name="fs_list_directory",
    description="List files and directories in the thoroughly sandboxed agent workspace.",
    category=ToolCategory.SYSTEM,
    parameters={"path": {"type": "string", "description": "Relative path within workspace", "default": "."}},
    requires_confirmation=False
)
async def fs_list_directory(path: str = ".") -> str:
    """List files and directories in the agent workspace."""
    target = _safe_resolve(path)
    if target is None:
        return "🚫 Access denied — path is outside the agent workspace."
    if not target.is_dir():
        return f"❌ '{path}' is not a directory."

    entries = sorted(target.iterdir())
    if not entries:
        return f"📂 '{path}' is empty."

    lines = [f"📂 Contents of `{path}`:"]
    for entry in entries[:50]:  # cap at 50 entries
        kind = "📁" if entry.is_dir() else "📄"
        size = f" ({entry.stat().st_size:,} bytes)" if entry.is_file() else ""
        lines.append(f"  {kind} {entry.name}{size}")
    return "\n".join(lines)


@tool(
    name="fs_read_file",
    description="Read the contents of a text file in the sandboxed agent workspace.",
    category=ToolCategory.SYSTEM,
    parameters={"path": {"type": "string", "description": "Relative path to file"}},
    requires_confirmation=False
)
async def fs_read_file(path: str) -> str:
    """Read the contents of a file in the agent workspace."""
    target = _safe_resolve(path)
    if target is None:
        return "🚫 Access denied — path is outside the agent workspace."
    if not target.is_file():
        return f"❌ '{path}' is not a file."

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        if len(content) > 5000:
            content = content[:5000] + "\n\n... [truncated — file exceeds 5000 chars]"
        return f"📄 **{path}**:\n```\n{content}\n```"
    except Exception as exc:
        return f"❌ Error reading file: {exc}"


@tool(
    name="fs_write_file",
    description="Write content to a file in the sandboxed agent workspace.",
    category=ToolCategory.SYSTEM,
    parameters={
        "path": {"type": "string", "description": "Relative path to file"},
        "content": {"type": "string", "description": "Content to write"}
    },
    requires_confirmation=True  # DESTRUCTIVE - REQUIRES HITL
)
async def fs_write_file(path: str, content: str) -> str:
    """Write content to a file in the agent workspace (creates dirs if needed)."""
    target = _safe_resolve(path)
    if target is None:
        return "🚫 Access denied — path is outside the agent workspace."

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"✅ File written: `{path}` ({len(content)} chars)"
    except Exception as exc:
        return f"❌ Error writing file: {exc}"


@tool(
    name="fs_search_files",
    description="Search for files by name pattern in the sandboxed agent workspace.",
    category=ToolCategory.SYSTEM,
    parameters={
        "query": {"type": "string", "description": "Search pattern"},
        "path": {"type": "string", "description": "Relative directory to search", "default": "."}
    },
    requires_confirmation=False
)
async def fs_search_files(query: str, path: str = ".") -> str:
    """Search for files matching a pattern in the agent workspace."""
    target = _safe_resolve(path)
    if target is None:
        return "🚫 Access denied — path is outside the agent workspace."
    if not target.is_dir():
        return f"❌ '{path}' is not a directory."

    matches = list(target.rglob(f"*{query}*"))[:20]
    if not matches:
        return f"🔍 No files matching '{query}' found."

    workspace = _get_workspace()
    lines = [f"🔍 Found {len(matches)} file(s) matching '{query}':"]
    for m in matches:
        rel = m.relative_to(workspace)
        lines.append(f"  📄 {rel}")
    return "\n".join(lines)


def build_filesystem_tools() -> list[Tool]:
    """Build sandboxed filesystem tools for the LLM tool registry."""
    return [
        fs_list_directory._tool_metadata,  # type: ignore[attr-defined]
        fs_read_file._tool_metadata,  # type: ignore[attr-defined]
        fs_write_file._tool_metadata,  # type: ignore[attr-defined]
        fs_search_files._tool_metadata,  # type: ignore[attr-defined]
    ]
