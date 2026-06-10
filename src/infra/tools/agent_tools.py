"""
Tools for the agent to proactively schedule and manage its own tasks.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from src.core.config import get_settings
from src.core.interfaces.repositories import IGoalRepository, ITaskRepository
from src.infra.tools.base import Tool, ToolCategory, tool


logger = logging.getLogger(__name__)

def build_agent_tools(
    memory_service: Any | None = None,
    goal_repository: IGoalRepository | None = None,
    task_repository: ITaskRepository | None = None,
    tool_registry: Any | None = None,
    llm_generate: Callable[[str], Awaitable[str]] | None = None,
    dispatch_background_event: Callable[[str], Awaitable[None]] | None = None,
) -> list[Tool]:
    """Return a list of LLM-callable agent tools with injected dependencies."""

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
        run_date = datetime.now() + timedelta(minutes=minutes)

        async def _execute_proactive_task() -> None:
            logger.info("Executing scheduled proactive task: %s for session %s", prompt, session_id)
            try:
                if dispatch_background_event:
                    await dispatch_background_event(prompt)
                else:
                    logger.warning("dispatch_background_event is not configured.")
            except Exception as e:
                logger.exception("Failed to execute proactive task: %s", e)

        try:
            async def _delayed_task() -> None:
                await asyncio.sleep(minutes * 60)
                await _execute_proactive_task()

            asyncio.create_task(_delayed_task())
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
            if not memory_service or not getattr(memory_service, "is_enabled", False):
                return "Memory service is not enabled."

            session_id = kwargs.get("session_id", "core")
            success = await memory_service.store(
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
            if not memory_service or not getattr(memory_service, "is_enabled", False):
                return "Memory service is not enabled."

            if hasattr(memory_service, "delete_by_text"):
                count = await memory_service.delete_by_text(fact)
                if count > 0:
                    return f"Successfully forgot {count} memory/memories matching: '{fact}'"
                return f"No memories found exactly matching: '{fact}'"
            return "Delete operation not supported by memory service."
        except Exception as e:
            logger.exception("Failed to forget memory: %s", e)
            return f"Error: {e}"

    @tool(
        name="create_goal",
        description="Create a long-term goal that spans multiple sessions. Use this when the user gives you a multi-step project or long-term objective.",
        category=ToolCategory.PRODUCTIVITY,
        parameters={
            "title": {"type": "string", "description": "Short title of the goal."},
            "description": {"type": "string", "description": "Detailed description of the goal and its success criteria."},
        },
    )
    async def create_goal(title: str, description: str, **kwargs: Any) -> str:
        """Create a new long-term goal."""
        try:
            if not goal_repository:
                return "Goal repository is not available."

            from src.core.domain.models import Goal, GoalStatus
            goal = Goal(
                title=title,
                description=description,
                status=GoalStatus.ACTIVE,
            )
            created = await goal_repository.create(goal)
            return f"Successfully created goal #{created.id}: {created.title}"
        except Exception as e:
            logger.exception("Failed to create goal: %s", e)
            return f"Error: {e}"

    @tool(
        name="update_goal",
        description="Update the status of a long-term goal. Use this to mark a goal as completed or abandoned.",
        category=ToolCategory.PRODUCTIVITY,
        parameters={
            "goal_id": {"type": "integer", "description": "The ID of the goal to update."},
            "status": {"type": "string", "description": "The new status: 'active', 'completed', or 'abandoned'."},
        },
    )
    async def update_goal(goal_id: int, status: str, **kwargs: Any) -> str:
        """Update a long-term goal."""
        try:
            if not goal_repository:
                return "Goal repository is not available."

            from src.core.domain.models import GoalStatus
            try:
                goal_status = GoalStatus(status.lower())
            except ValueError:
                return f"Invalid status '{status}'. Must be active, completed, or abandoned."

            goal = await goal_repository.get_by_id(goal_id)
            if not goal:
                return f"Goal #{goal_id} not found."

            if goal_status == GoalStatus.COMPLETED:
                goal = await goal_repository.mark_complete(goal_id)
            else:
                goal.status = goal_status
                goal = await goal_repository.update(goal)

            return f"Successfully updated goal #{goal.id} to {goal.status.value}"
        except Exception as e:
            logger.exception("Failed to update goal: %s", e)
            return f"Error: {e}"

    @tool(
        name="list_active_goals",
        description="List all currently active long-term goals.",
        category=ToolCategory.PRODUCTIVITY,
        parameters={},
    )
    async def list_active_goals(**kwargs: Any) -> str:
        """List active long-term goals."""
        try:
            if not goal_repository:
                return "Goal repository is not available."

            goals = await goal_repository.get_active()
            if not goals:
                return "No active goals found."

            lines = ["Active Goals:"]
            for g in goals:
                lines.append(f"#{g.id}: {g.title} (Created: {g.created_at.strftime('%Y-%m-%d')})")
                if g.description:
                    lines.append(f"  Description: {g.description}")
            return "\n".join(lines)
        except Exception as e:
            logger.exception("Failed to list active goals: %s", e)
            return f"Error: {e}"

    @tool(
        name="manage_plugins",
        description="List, add, or remove plugins for Amadeus. Use this to extend your own capabilities. Actions: 'list', 'add', 'remove'.",
        category=ToolCategory.SYSTEM,
        parameters={
            "action": {"type": "string", "description": "Action to perform: 'list', 'add', 'remove'"},
            "plugin_name": {"type": "string", "description": "Name of the plugin file (e.g., 'my_tool.py')", "default": ""},
            "content": {"type": "string", "description": "Content of the plugin file (for 'add' action)", "default": ""},
        },
        requires_confirmation=True,
    )
    async def manage_plugins(action: str, plugin_name: str = "", content: str = "", **kwargs: Any) -> str:
        """Manage Amadeus plugins."""
        settings = get_settings()
        plugins_dir = settings.BASE_DIR / "plugins"
        plugins_dir.mkdir(parents=True, exist_ok=True)

        if action == "list":
            plugins = list(plugins_dir.glob("*.py"))
            if not plugins:
                return "No plugins found in the plugins directory."
            return "Available plugins:\n" + "\n".join(f"- {p.name}" for p in plugins)

        if action == "add":
            if not plugin_name or not content:
                return "Error: plugin_name and content are required for 'add' action."
            if not plugin_name.endswith(".py"):
                plugin_name += ".py"

            plugin_path = plugins_dir / plugin_name
            plugin_path.write_text(content, encoding="utf-8")

            if tool_registry:
                tool_registry.discover_plugins(plugins_dir)

            return f"Successfully added plugin: {plugin_name}. New tools have been registered."

        if action == "remove":
            if not plugin_name:
                return "Error: plugin_name is required for 'remove' action."
            if not plugin_name.endswith(".py"):
                plugin_name += ".py"

            plugin_path = plugins_dir / plugin_name
            if not plugin_path.exists():
                return f"Error: Plugin {plugin_name} not found."

            plugin_path.unlink()
            return f"Successfully removed plugin: {plugin_name}. Note: Registered tools from this plugin will persist until restart."

        return f"Unknown action: {action}"

    @tool(
        name="search_codebase",
        description="Search through the Amadeus-AI codebase to understand your own implementation. Useful for self-improvement or debugging.",
        category=ToolCategory.SYSTEM,
        parameters={
            "query": {"type": "string", "description": "Text pattern to search for"},
            "file_pattern": {"type": "string", "description": "File pattern to filter (e.g., '*.py')", "default": "*"},
        },
    )
    async def search_codebase(query: str, file_pattern: str = "*", **kwargs: Any) -> str:
        """Search the codebase."""
        settings = get_settings()
        try:
            target_dir = str(settings.BASE_DIR / "src")
            # Safely pass arguments as a list without shell formatting
            args = ["grep", "-r", "-l", f"--include={file_pattern}", query, target_dir]

            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10.0)
            except TimeoutError:
                process.kill()
                await process.wait()
                return f"Error: search for '{query}' timed out after 10 seconds."

            out = stdout.decode("utf-8", errors="replace").strip()
            err = stderr.decode("utf-8", errors="replace").strip()

            if process.returncode != 0:
                return f"No matches found for '{query}' in {file_pattern}. {err}"

            files = out.split("\n")
            return f"Found '{query}' in {len(files)} files:\n" + "\n".join(f"- {f}" for f in files[:10])
        except Exception as e:
            return f"Error searching codebase: {e}"

    @tool(
        name="decompose_goal",
        description="Breaks down a high-level goal into smaller, actionable sub-tasks and adds them to your task list.",
        category=ToolCategory.PRODUCTIVITY,
        parameters={
            "goal_id": {"type": "integer", "description": "The ID of the parent goal to decompose."},
        },
    )
    async def decompose_goal(goal_id: int, **kwargs: Any) -> str:
        """Decompose a goal into tasks and save them."""
        try:
            if not goal_repository:
                return "Goal repository is not available."
            if not task_repository:
                return "Task repository is not available."

            goal = await goal_repository.get_by_id(goal_id)
            if not goal:
                return f"Goal #{goal_id} not found."

            if not llm_generate:
                return "LLM not available for decomposition."

            prompt = f"""You are Amadeus. Break down the following goal into 3-5 actionable sub-tasks.
Goal: {goal.title}
Description: {goal.description}

Respond ONLY with a list of tasks, one per line, without numbers or bullets. Just the plain text task description.
"""
            response = await llm_generate(prompt)
            tasks_text = [line.strip("- ").strip() for line in response.strip().split("\n") if line.strip()]

            if not tasks_text:
                return "Failed to generate sub-tasks."

            from src.core.domain.models import Task
            created_tasks = []
            for task_desc in tasks_text:
                created = await task_repository.create(Task(content=task_desc))
                created_tasks.append(created)

            lines = [f"Decomposed Goal #{goal_id} ('{goal.title}') into {len(created_tasks)} tasks added to your task list:"]
            for i, task in enumerate(created_tasks, 1):
                lines.append(f"{i}. [{task.id}] {task.content}")

            return "\n".join(lines)
        except Exception as e:
            logger.exception("Failed to decompose goal: %s", e)
            return f"Error: {e}"

    return [
        schedule_future_task._tool_metadata,  # type: ignore[attr-defined]
        store_core_memory._tool_metadata,  # type: ignore[attr-defined]
        forget_core_memory._tool_metadata,  # type: ignore[attr-defined]
        create_goal._tool_metadata,  # type: ignore[attr-defined]
        update_goal._tool_metadata,  # type: ignore[attr-defined]
        list_active_goals._tool_metadata,  # type: ignore[attr-defined]
        manage_plugins._tool_metadata,  # type: ignore[attr-defined]
        search_codebase._tool_metadata,  # type: ignore[attr-defined]
        decompose_goal._tool_metadata,  # type: ignore[attr-defined]
    ]
