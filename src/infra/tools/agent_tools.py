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
        run_date = datetime.now() + timedelta(minutes=minutes)

        async def _execute_proactive_task() -> None:
            logger.info("Executing scheduled proactive task: %s for session %s", prompt, session_id)
            try:
                from src.container import get_amadeus_service
                svc = get_amadeus_service()
                await svc.handle_background_event(prompt)
            except Exception as e:
                logger.exception("Failed to execute proactive task: %s", e)

        try:
            # Schedule via asyncio: create the coroutine to run after `minutes` delay
            async def _delayed_task() -> None:
                await asyncio.sleep(minutes * 60)
                await _execute_proactive_task()

            import asyncio as _asyncio
            _asyncio.create_task(_delayed_task())
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
            from src.container import get_amadeus_service
            svc = get_amadeus_service()
            if not svc.goal_repository:
                return "Goal repository is not available."

            from src.core.domain.models import Goal, GoalStatus
            goal = Goal(
                title=title,
                description=description,
                status=GoalStatus.ACTIVE,
            )
            created = await svc.goal_repository.create(goal)
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
            from src.container import get_amadeus_service
            svc = get_amadeus_service()
            if not svc.goal_repository:
                return "Goal repository is not available."

            from src.core.domain.models import GoalStatus
            try:
                goal_status = GoalStatus(status.lower())
            except ValueError:
                return f"Invalid status '{status}'. Must be active, completed, or abandoned."

            goal = await svc.goal_repository.get_by_id(goal_id)
            if not goal:
                return f"Goal #{goal_id} not found."

            if goal_status == GoalStatus.COMPLETED:
                goal = await svc.goal_repository.mark_complete(goal_id)
            else:
                goal.status = goal_status
                goal = await svc.goal_repository.update(goal)

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
            from src.container import get_amadeus_service
            svc = get_amadeus_service()
            if not svc.goal_repository:
                return "Goal repository is not available."

            goals = await svc.goal_repository.get_active()
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

        from src.core.config import get_settings

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

            # Trigger re-discovery
            from src.container import get_tool_registry
            registry = get_tool_registry()
            registry.discover_plugins(plugins_dir)

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
        import shlex
        import subprocess

        from src.core.config import get_settings

        settings = get_settings()
        try:
            # Use grep to search (ripgrep if available, fallback to grep)
            cmd = f"grep -r -l --include='{file_pattern}' '{query}' {settings.BASE_DIR / 'src'}"
            args = shlex.split(cmd)
            result = subprocess.run(args, capture_output=True, text=True, timeout=10)

            if result.returncode != 0:
                return f"No matches found for '{query}' in {file_pattern}."

            files = result.stdout.strip().split("\n")
            return f"Found '{query}' in {len(files)} files:\n" + "\n".join(f"- {f}" for f in files[:10])
        except Exception as e:
            return f"Error searching codebase: {e}"

    @tool(
        name="decompose_goal",
        description="Breaks down a high-level goal into smaller, actionable sub-tasks. Useful for complex projects.",
        category=ToolCategory.PRODUCTIVITY,
        parameters={
            "goal_id": {"type": "integer", "description": "The ID of the parent goal to decompose."},
        },
    )
    async def decompose_goal(goal_id: int, **kwargs: Any) -> str:
        """Decompose a goal into tasks."""
        try:
            from src.container import get_amadeus_service
            svc = get_amadeus_service()
            if not svc.goal_repository:
                return "Goal repository is not available."

            goal = await svc.goal_repository.get_by_id(goal_id)
            if not goal:
                return f"Goal #{goal_id} not found."

            # Use LLM to generate sub-tasks
            prompt = f"""You are Amadeus. Break down the following goal into 3-5 actionable sub-tasks.
Goal: {goal.title}
Description: {goal.description}

Respond ONLY with a list of tasks, one per line.
Tasks:"""
            llm_generate = svc._make_llm_generate()
            if not llm_generate:
                return "LLM not available for decomposition."

            response = await llm_generate(prompt)
            tasks = [line.strip("- ").strip() for line in response.strip().split("\n") if line.strip()]

            if not tasks:
                return "Failed to generate sub-tasks."


            # This is a bit tricky due to repository access, but let's assume we can add them
            # For simplicity in this tool, we'll just return the suggested tasks.
            # A more complete implementation would save them to the DB linked to the goal.

            lines = [f"Decomposition for Goal #{goal_id} ('{goal.title}'):"]
            for i, task_text in enumerate(tasks, 1):
                lines.append(f"{i}. {task_text}")

            return "\n".join(lines)
        except Exception as e:
            logger.exception("Failed to decompose goal: %s", e)
            return f"Error: {e}"

    return [
        schedule_future_task._tool_metadata,
        store_core_memory._tool_metadata,
        forget_core_memory._tool_metadata,
        create_goal._tool_metadata,
        update_goal._tool_metadata,
        list_active_goals._tool_metadata,
        manage_plugins._tool_metadata,
        search_codebase._tool_metadata,
        decompose_goal._tool_metadata,
    ]
