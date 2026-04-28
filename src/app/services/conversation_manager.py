"""
Conversation Manager for Amadeus AI.

Handles in-memory caching of conversation history synchronized with
an optional persistent database repository (source of truth).

Separated from AmadeusService to respect Single Responsibility Principle.

Note: ``ConversationMessage`` is the canonical Pydantic model from
``src.core.domain.models`` — no duplicate dataclass is defined here.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

# Re-export the single canonical model — no local dataclass.
from src.core.domain.models import ConversationMessage

__all__ = ["ConversationMessage", "ConversationManager", "IConversationRepository"]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Repository Protocol (kept local to avoid circular imports)
# ---------------------------------------------------------------------------


class IConversationRepository:
    """Structural protocol — any object implementing these methods is accepted."""

    async def add_message(
        self, session_id: str, role: str, content: str, tool_used: str | None = None
    ) -> None: ...

    async def get_recent_context(
        self, session_id: str, limit: int = 20
    ) -> list[dict[str, Any]]: ...

    async def clear_session(self, session_id: str) -> None: ...


# ---------------------------------------------------------------------------
# ConversationManager
# ---------------------------------------------------------------------------


class ConversationManager:
    """
    Manages conversation history with UNIFIED storage.

    When a repository is provided, ALL writes go through the database first
    (source of truth). The in-memory cache is a read-optimized view of the
    most recent messages, always kept in sync.

    This design solves the "dual memory split" problem where in-memory and
    DB state diverge after a server restart.
    """

    def __init__(
        self,
        session_id: str,
        repo: IConversationRepository | None = None,
        max_context: int = 20,
    ) -> None:
        self.session_id = session_id
        self.repo = repo
        self.max_context = max_context

        # In-memory cache (synchronized with DB)
        self._cache: list[ConversationMessage] = []
        self._cache_loaded = False

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def add(
        self, role: str, content: str, tool_used: str | None = None, **metadata: Any
    ) -> None:
        """Add a message — persists to DB first, then updates the cache."""
        msg = ConversationMessage(
            role=role,
            content=content,
            tool_used=tool_used,
            timestamp=datetime.now(UTC),
            metadata=dict(metadata),
        )

        # DB is source of truth — write there first
        if self.repo:
            await self.repo.add_message(
                session_id=self.session_id,
                role=role,
                content=content,
                tool_used=tool_used,
            )

        self._cache.append(msg)
        self._trim_cache()

    async def clear(self) -> None:
        """Clear history from both the DB and the in-memory cache."""
        if self.repo:
            await self.repo.clear_session(self.session_id)
        self._cache.clear()
        self._cache_loaded = False

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_messages(self) -> list[ConversationMessage]:
        """Return all cached messages (most-recent up to max_context)."""
        return self._cache

    def get_formatted_history(self, last_n: int = 5) -> str:
        """Return a formatted string of the last N turns for prompt injection."""
        recent = self._cache[-last_n:] if len(self._cache) > last_n else self._cache
        parts: list[str] = []
        for msg in recent:
            prefix = "User" if msg.role == "user" else "Amadeus"
            tool_info = f" [used: {msg.tool_used}]" if msg.tool_used else ""
            parts.append(f"{prefix}{tool_info}: {msg.content}")
        return "\n".join(parts)

    def get_context_summary(self) -> str:
        """Return a one-line summary of recent topics and tools for the system prompt."""
        if not self._cache:
            return "No prior conversation."

        tools_used = [m.tool_used for m in self._cache if m.tool_used]
        topics: set[str] = set()
        topic_keywords = ["weather", "news", "task", "reminder", "note", "file", "time", "system"]
        for m in self._cache[-5:]:
            words = m.content.lower().split()
            for kw in topic_keywords:
                if kw in words:
                    topics.add(kw)

        return (
            f"Recent topics: {', '.join(topics) or 'general'}. "
            f"Tools used: {', '.join(set(tools_used[-3:])) or 'none'}."
        )

    # ------------------------------------------------------------------
    # Startup hydration
    # ------------------------------------------------------------------

    async def load_from_db(self) -> None:
        """Populate the in-memory cache from the DB on service startup."""
        if not self.repo or self._cache_loaded:
            return

        try:
            messages = await self.repo.get_recent_context(
                session_id=self.session_id,
                limit=self.max_context,
            )
            self._cache = [
                ConversationMessage(
                    role=m["role"],
                    content=m["content"],
                    tool_used=m.get("tool_used"),
                    timestamp=(
                        datetime.fromisoformat(m["timestamp"])
                        if m.get("timestamp")
                        else datetime.now(UTC)
                    ),
                )
                for m in messages
            ]
            self._cache_loaded = True
            logger.info(
                "Loaded %d messages from DB for session %s...",
                len(self._cache),
                self.session_id[:8],
            )
        except Exception:
            logger.exception("Failed to load conversation history from DB")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _trim_cache(self) -> None:
        """Discard oldest messages if cache exceeds max_context."""
        if len(self._cache) > self.max_context:
            self._cache = self._cache[-self.max_context :]
