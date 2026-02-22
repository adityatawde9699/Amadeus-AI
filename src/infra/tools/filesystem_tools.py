"""
Sandboxed Filesystem Tools for Amadeus AI.

All file operations are strictly confined to the agent workspace
directory (DATA_DIR/agent_workspace). Directory traversal is blocked.
"""

import logging
from pathlib import Path
from typing import Any

from src.core.config import get_settings


logger = logging.getLogger(__name__)


def _get_workspace() -> Path:
    """Get the sandboxed workspace directory, creating it if needed."""
    settings = get_settings()
    workspace = settings.DATA_DIR / "agent_workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


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


def build_filesystem_tools() -> list[dict[str, Any]]:
    """Build sandboxed filesystem tools for the LLM tool registry."""

    async def list_directory(path: str = ".") -> str:
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

    async def read_file(path: str) -> str:
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

    async def write_file(path: str, content: str) -> str:
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

    async def search_files(query: str, path: str = ".") -> str:
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

    return [
        {
            "name": "list_directory",
            "description": "List files and directories in the agent workspace.",
            "function": list_directory,
            "parameters": {"path": {"type": "string", "description": "Relative path within workspace", "default": "."}},
        },
        {
            "name": "read_file",
            "description": "Read the contents of a text file in the agent workspace.",
            "function": read_file,
            "parameters": {"path": {"type": "string", "description": "Relative path to file"}},
        },
        {
            "name": "write_file",
            "description": "Write content to a file in the agent workspace.",
            "function": write_file,
            "parameters": {
                "path": {"type": "string", "description": "Relative path to file"},
                "content": {"type": "string", "description": "Content to write"},
            },
        },
        {
            "name": "search_files",
            "description": "Search for files by name pattern in the agent workspace.",
            "function": search_files,
            "parameters": {
                "query": {"type": "string", "description": "Search pattern"},
                "path": {"type": "string", "description": "Relative directory to search", "default": "."},
            },
        },
    ]
