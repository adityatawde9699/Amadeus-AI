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
    description=(
        "Lists all files and subdirectories in the sandboxed agent workspace (max 50 entries). "
        "Shows file sizes and directory indicators. Only works within the agent workspace — "
        "cannot access files outside this sandbox. "
        "Trigger: 'list workspace files', 'show agent directory', 'what files do you have'"
    ),
    category=ToolCategory.FILE_SYSTEM,
    parameters={
        "path": {"type": "string", "description": "Relative path within workspace (use '.' for root)", "default": "."}
    },
    requires_confirmation=False,
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
    description=(
        "Reads and returns the text content of a file in the sandboxed agent workspace "
        "(truncated at 5000 characters for large files). Cannot access files outside the workspace. "
        "Trigger: 'read file X', 'show me the contents of', 'cat this file'"
    ),
    category=ToolCategory.FILE_SYSTEM,
    parameters={"path": {"type": "string", "description": "Relative path to file"}},
    requires_confirmation=False,
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
    description=(
        "Writes text content to a file in the sandboxed agent workspace. Creates parent "
        "directories if they don't exist. Requires confirmation before writing (destructive). "
        "Trigger: 'write to file', 'save this to a file', 'create a text file'"
    ),
    category=ToolCategory.FILE_SYSTEM,
    parameters={
        "path": {"type": "string", "description": "Relative path to file"},
        "content": {"type": "string", "description": "Content to write"},
    },
    requires_confirmation=True,  # DESTRUCTIVE - REQUIRES HITL
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
    description=(
        "Searches for files by name pattern within the sandboxed agent workspace. "
        "Returns up to 20 matching file paths. Uses glob-style matching. "
        "Trigger: 'search workspace for', 'find file in workspace', 'locate workspace file'"
    ),
    category=ToolCategory.FILE_SYSTEM,
    parameters={
        "query": {"type": "string", "description": "Search pattern"},
        "path": {"type": "string", "description": "Relative directory to search", "default": "."},
    },
    requires_confirmation=False,
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
