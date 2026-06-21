"""
Task notification domain models (Telegram conversation-only mode, v5).

In command-and-control mode Telegram is a *notification channel*: instead of
streaming full results, generated content, logs, or reasoning chains, Amadeus
sends short status updates and pointers to where the real output was saved.

These models are transport-agnostic — ``render()`` produces a compact, safe
string that any transport (Telegram, CLI, email) can deliver.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from src.core.domain.artifacts import ArtifactRef


class NotificationKind(StrEnum):
    """The lifecycle stage a notification reports."""

    ACCEPTED = "accepted"
    STARTED = "started"
    PROGRESS = "progress"
    COMPLETED = "completed"
    FAILED = "failed"
    INFO = "info"


_ICONS: dict[NotificationKind, str] = {
    NotificationKind.ACCEPTED: "📥",
    NotificationKind.STARTED: "▶️",
    NotificationKind.PROGRESS: "⏳",
    NotificationKind.COMPLETED: "✅",
    NotificationKind.FAILED: "⚠️",
    NotificationKind.INFO: "ℹ️",
}


@dataclass(frozen=True)
class TaskNotification:
    """A single status update destined for a command-and-control channel.

    Attributes:
        kind: Which lifecycle stage this reports.
        title: Short human label, e.g. ``"Research"`` or ``"Code generation"``.
        detail: Optional one-line detail (kept short — no reasoning chains).
        artifacts: Saved-output pointers to surface (paths only, never bodies).
        error: User-safe error message (already sanitised — no stack traces).
    """

    kind: NotificationKind
    title: str
    detail: str | None = None
    artifacts: tuple[ArtifactRef, ...] = field(default_factory=tuple)
    error: str | None = None

    # ------------------------------------------------------------------
    # Convenience constructors
    # ------------------------------------------------------------------
    @classmethod
    def accepted(cls, title: str, detail: str | None = None) -> TaskNotification:
        return cls(NotificationKind.ACCEPTED, title, detail)

    @classmethod
    def started(cls, title: str, detail: str | None = None) -> TaskNotification:
        return cls(NotificationKind.STARTED, title, detail)

    @classmethod
    def progress(cls, title: str, detail: str) -> TaskNotification:
        return cls(NotificationKind.PROGRESS, title, detail)

    @classmethod
    def completed(
        cls,
        title: str,
        artifacts: tuple[ArtifactRef, ...] = (),
        detail: str | None = None,
    ) -> TaskNotification:
        return cls(NotificationKind.COMPLETED, title, detail, artifacts=artifacts)

    @classmethod
    def failed(cls, title: str, error: str) -> TaskNotification:
        return cls(NotificationKind.FAILED, title, error=error)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def render(self) -> str:
        """Render a compact, channel-safe message string."""
        icon = _ICONS.get(self.kind, "")
        verb = {
            NotificationKind.ACCEPTED: "accepted",
            NotificationKind.STARTED: "started",
            NotificationKind.PROGRESS: "in progress",
            NotificationKind.COMPLETED: "completed",
            NotificationKind.FAILED: "failed",
            NotificationKind.INFO: "",
        }[self.kind]

        if self.kind is NotificationKind.INFO:
            header = f"{icon} {self.detail or self.title}".strip()
        else:
            header = f"{icon} {self.title} {verb}.".strip()

        lines = [header]

        if self.kind is not NotificationKind.INFO and self.detail:
            lines.append(self.detail)

        if self.error:
            lines.append(self.error)

        if self.artifacts:
            if len(self.artifacts) == 1:
                lines.append(f"Output saved to:\n{self.artifacts[0].display_path}")
            else:
                lines.append("Output saved to:")
                lines.extend(f"• {a.display_path}" for a in self.artifacts)

        return "\n".join(lines)
