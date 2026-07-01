"""
CommandRouter — explicit command-and-control entry point (v5).

In conversation-only mode, certain inputs are *commands*, not chat: they kick
off a task whose output is persisted to AMASPACE while the channel receives
only status notifications. The canonical example is::

    Research <topic>

This router recognises such commands, executes them via the appropriate
application service (the Research Engine), and drives a notification callback
through the task lifecycle (started → [progress] → completed / failed).

It is transport-agnostic: the caller supplies a ``notify`` coroutine, so the
same router works for Telegram, CLI, or any future channel.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.core.domain.notifications import TaskNotification


if TYPE_CHECKING:
    from src.research.orchestrator import ResearchOrchestrator


logger = logging.getLogger(__name__)

NotifyCallback = Callable[[TaskNotification], Awaitable[None]]

# Leading verbs that introduce a research command.
_RESEARCH_PREFIXES = ("research ", "/research ", "deep research ", "deep-research ")


@dataclass(frozen=True)
class ParsedCommand:
    name: str
    argument: str


class CommandRouter:
    def __init__(
        self,
        research_orchestrator: ResearchOrchestrator | None = None,
        *,
        forward_progress: bool = False,
    ) -> None:
        self._research = research_orchestrator
        self._forward_progress = forward_progress

    # ------------------------------------------------------------------
    def parse(self, text: str) -> ParsedCommand | None:
        """Return a ParsedCommand if *text* is a recognised command, else None."""
        stripped = text.strip()
        lowered = stripped.lower()
        for prefix in _RESEARCH_PREFIXES:
            if lowered.startswith(prefix):
                topic = stripped[len(prefix):].strip()
                if topic:
                    return ParsedCommand(name="research", argument=topic)
        return None

    async def try_handle(
        self,
        text: str,
        *,
        notify: NotifyCallback,
        request_id: str | None = None,
        session_id: str | None = None,
    ) -> bool:
        """Execute *text* as a command if recognised.

        Returns True when the input was handled as a command (so the caller
        should NOT fall through to the conversational pipeline), False otherwise.
        """
        parsed = self.parse(text)
        if parsed is None:
            return False

        if parsed.name == "research":
            await self._handle_research(parsed.argument, notify, request_id, session_id)
            return True

        return False

    # ------------------------------------------------------------------
    async def _handle_research(
        self,
        topic: str,
        notify: NotifyCallback,
        request_id: str | None,
        session_id: str | None,
    ) -> None:
        title = "Research"
        if self._research is None:
            await notify(
                TaskNotification.failed(title, "Research engine is not available.")
            )
            return

        await notify(TaskNotification.started(title, detail=f"Topic: {topic}"))

        async def _progress(msg: str) -> None:
            if self._forward_progress:
                await notify(TaskNotification.progress(title, msg))
            else:
                logger.info("research_progress: %s", msg)

        try:
            result = await self._research.run(
                topic,
                request_id=request_id,
                session_id=session_id,
                progress=_progress,
            )
        except Exception as exc:
            logger.exception("research command failed for topic=%r", topic)
            await notify(
                TaskNotification.failed(
                    title, f"Research failed: {type(exc).__name__}."
                )
            )
            return

        detail = (
            f"Topic: {topic} — {result.manifest.source_count} source(s), "
            f"{result.manifest.question_count} question(s)."
        )
        await notify(
            TaskNotification.completed(title, artifacts=tuple(result.artifacts), detail=detail)
        )
