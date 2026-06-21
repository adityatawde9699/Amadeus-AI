"""
OutputDeliveryPolicy — enforces Telegram conversation-only mode (v5).

This is the central gate every chat reply passes through before it reaches the
channel. It guarantees that large outputs — full reports, generated documents,
code files, execution logs, reasoning chains — are persisted to AMASPACE and
replaced with a short notification + the saved path, instead of being dumped
into the chat.

Because the policy lives at the delivery boundary (not inside any one tool),
*every* current and future tool inherits the behaviour automatically: whatever
a tool returns, if it's big, it gets saved and only its location is announced.

Short, genuinely conversational replies pass through unchanged so command-and-
control still feels like a conversation.
"""

from __future__ import annotations

import logging

from src.core.config import Settings
from src.core.domain.artifacts import Artifact, ArtifactType
from src.core.domain.notifications import NotificationKind, TaskNotification
from src.infra.workspace.storage_service import StorageService


logger = logging.getLogger(__name__)


class OutputDeliveryPolicy:
    def __init__(self, storage_service: StorageService, settings: Settings) -> None:
        self._storage = storage_service
        self._settings = settings

    def deliver(
        self,
        response: str,
        *,
        request_id: str | None = None,
        session_id: str | None = None,
        title: str = "Task",
    ) -> str:
        """Return the text that should actually be sent to the channel.

        When notification-only mode is on and *response* exceeds the configured
        size, the full body is persisted to ``AMASPACE/exports`` and a path
        notification is returned in its place.
        """
        if not getattr(self._settings, "TELEGRAM_NOTIFICATION_ONLY", True):
            return response

        text = response or ""
        if len(text) <= self._settings.TELEGRAM_MAX_REPLY_CHARS:
            return text

        try:
            ref = self._storage.persist(
                Artifact(
                    artifact_type=ArtifactType.EXPORT,
                    title=_derive_title(text),
                    content=text,
                    origin="chat",
                    content_type="text/markdown",
                    request_id=request_id,
                    session_id=session_id,
                    tags=("chat", "export"),
                )
            )
        except Exception:
            # Never fail a reply because persistence broke — fall back to a
            # truncated, trace-free message.
            logger.exception("output_policy: failed to persist large reply")
            return TaskNotification(
                kind=NotificationKind.COMPLETED,
                title=title,
                detail="Output was too large to display and could not be saved.",
            ).render()

        logger.info("output_policy: large reply persisted to %s", ref.display_path)
        return TaskNotification.completed(title, artifacts=(ref,)).render()


def _derive_title(text: str) -> str:
    """Use the first non-empty line as a human title (bounded)."""
    for line in text.splitlines():
        cleaned = line.strip().lstrip("# ").strip()
        if cleaned:
            return cleaned[:80]
    return "Chat output"
