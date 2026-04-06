"""
Tools for the agent to proactively schedule and manage its own tasks.
"""
import logging
from datetime import datetime, timedelta

from typing import Any

from src.infra.tools.base import Tool, ToolCategory, tool


logger = logging.getLogger(__name__)

def get_agent_tools() -> list[Any]:
    """Return a list of LLM-callable agent tools."""

    @tool(
        name="schedule_future_task",
        description="Schedule a task for yourself to perform in the future. Useful for setting reminders, delayed actions, or proactive follow-ups.",
        category=ToolCategory.PRODUCTIVITY,
        parameters={
            "minutes": {"type": "integer", "description": "Minutes from now to execute the task"},
            "prompt": {"type": "string", "description": "The prompt or instruction you should execute when the time comes"},
            "session_id": {"type": "string", "description": "The current conversation session ID to preserve context."}
        }
    )
    async def schedule_future_task(minutes: int, prompt: str, session_id: str) -> str:
        """Schedule a task for the agent to execute proactively."""
        try:
            from src.api.server import scheduler
        except ImportError as e:
            logger.exception(f"Cannot import scheduler: {e}")
            return "Failed to access system scheduler."

        run_date = datetime.now() + timedelta(minutes=minutes)

        async def _execute_proactive_task(task_prompt: str, s_id: str) -> None:
            logger.info(f"Executing scheduled proactive task: {task_prompt} for session {s_id}")
            try:
                from src.app.services.amadeus_service import AmadeusService
                # Initialize the service for the given session
                svc = AmadeusService(session_id=s_id)
                await svc.initialize()
                await svc.handle_background_event(task_prompt)
            except Exception as e:
                logger.exception(f"Failed to execute proactive task: {e}")

        try:
            scheduler.add_job(
                _execute_proactive_task,
                "date",
                run_date=run_date,
                args=[prompt, session_id]
            )
            return f"Successfully scheduled task to execute in {minutes} minutes at {run_date.strftime('%H:%M:%S')}."
        except Exception as e:
            logger.exception(f"Failed to schedule future task: {e}")
            return f"Failed to schedule task: {e}"

    return [schedule_future_task]
