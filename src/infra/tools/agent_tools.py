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

    @tool(
        name="store_core_memory",
        description="Permanently store a fact about the user or your system instructions in core memory. Use this when the user says 'remember that I...', 'my name is...', or 'always do X'.",
        category=ToolCategory.SYSTEM,
        parameters={
            "fact": {
                "type": "string",
                "description": "The exact fact to remember. Keep it concise but fully self-contained.",
            }
        },
    )
    async def store_core_memory(fact: str, **kwargs: Any) -> str:
        """Store a fact in long-term memory."""
        try:
            from src.container import get_amadeus_service
            svc = get_amadeus_service()
            if not svc.memory_service or not svc.memory_service.is_enabled:
                return "Memory service is not enabled."
            
            # Use 'identity' subtype so it never decays.
            session_id = kwargs.get("session_id", "core")
            success = await svc.memory_service.store(
                session_id=session_id,
                role="system",
                text=fact,
                subtype="identity",
                importance=1.0,
            )
            if success:
                return f"Successfully stored memory: '{fact}'"
            return "Failed to store memory (internal error)."
        except Exception as e:
            logger.exception("Failed to store memory: %s", e)
            return f"Error: {e}"

    @tool(
        name="forget_core_memory",
        description="Delete a previously stored fact from core memory. Use this if the user says 'forget that I...' or 'I changed my mind about...'",
        category=ToolCategory.SYSTEM,
        parameters={
            "fact": {
                "type": "string",
                "description": "The exact text of the fact to forget.",
            }
        },
    )
    async def forget_core_memory(fact: str, **kwargs: Any) -> str:
        """Remove a fact from long-term memory."""
        try:
            from src.container import get_amadeus_service
            svc = get_amadeus_service()
            if not svc.memory_service or not svc.memory_service.is_enabled:
                return "Memory service is not enabled."
            
            # Accessing the new delete_by_text method
            if hasattr(svc.memory_service, "delete_by_text"):
                count = await svc.memory_service.delete_by_text(fact)
                if count > 0:
                    return f"Successfully forgot {count} memory/memories matching: '{fact}'"
                return f"No memories found exactly matching: '{fact}'"
            return "Delete operation not supported by memory service."
        except Exception as e:
            logger.exception("Failed to forget memory: %s", e)
            return f"Error: {e}"

    return [
        schedule_future_task._tool_metadata,
        store_core_memory._tool_metadata,
        forget_core_memory._tool_metadata,
    ]
