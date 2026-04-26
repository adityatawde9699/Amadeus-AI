"""
Tools for the agent to proactively schedule and manage its own tasks.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from src.infra.tools.base import ToolCategory, tool


logger = logging.getLogger(__name__)


def get_agent_tools() -> list[Any]:
    """Return a list of LLM-callable agent tools."""

    @tool(
        name="schedule_future_task",
        description="Schedule a task for yourself to perform in the future. Useful for setting reminders, delayed actions, or proactive follow-ups.",
        category=ToolCategory.PRODUCTIVITY,
        parameters={
            "minutes": {"type": "integer", "description": "Minutes from now to execute the task"},
            "prompt": {
                "type": "string",
                "description": "The prompt or instruction you should execute when the time comes",
            },
            "session_id": {
                "type": "string",
                "description": "The current conversation session ID to preserve context.",
            },
        },
    )
    async def schedule_future_task(minutes: int, prompt: str, session_id: str) -> str:
        """Schedule a task for the agent to execute proactively."""
        try:
            from src.api.server import scheduler
        except ImportError as e:
            logger.exception("Cannot import scheduler: %s", e)
            return "Failed to access system scheduler."

        run_date = datetime.now() + timedelta(minutes=minutes)

        async def _execute_proactive_task(task_prompt: str, s_id: str) -> None:
            logger.info("Executing scheduled proactive task: %s for session %s", task_prompt, s_id)
            try:
                # Use the container singleton — NOT a bare AmadeusService() —
                # so it gets llm_router, tool_registry, and cache_service injected.
                from src.container import get_amadeus_service

                svc = get_amadeus_service()
                await svc.handle_background_event(task_prompt)
            except Exception as e:
                logger.exception("Failed to execute proactive task: %s", e)

        try:
            scheduler.add_job(
                _execute_proactive_task, "date", run_date=run_date, args=[prompt, session_id]
            )
            return f"Successfully scheduled task to execute in {minutes} minutes at {run_date.strftime('%H:%M:%S')}."
        except Exception as e:
            logger.exception("Failed to schedule future task: %s", e)
            return f"Failed to schedule task: {e}"

    return [schedule_future_task._tool_metadata]
