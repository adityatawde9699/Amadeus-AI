"""
Productivity tools for Amadeus AI Assistant.

Refactored to use injected repositories (Phase 3) instead of direct DB sessions.

Pattern:
  - `build_task_tools(repo)` — factory returning Tool list with injected ITaskRepository
  - `build_pomodoro_tools(repo)` — factory returning Tool list with injected IPomodoroRepository
  - `get_productivity_tools()` — legacy helper for registry auto-discovery (no injection)

The container.py calls `build_*_tools(repo)` at startup and registers them.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from src.core.domain.models import Note, PomodoroSession, PomodoroState, Reminder
from src.core.interfaces.repositories import (
    INoteRepository,
    IPomodoroRepository,
    IReminderRepository,
    ITaskRepository,
)
from src.infra.tools.base import Tool, ToolCategory, tool


logger = logging.getLogger(__name__)


# =============================================================================
# LEGACY DB SESSION HELPER (kept for backwards compat — will be deprecated)
# The injected factory functions below are the preferred approach.
# =============================================================================


def _get_session() -> Any:
    """Get async session — used by legacy bare-function tools."""
    from src.infra.persistence.database import get_session

    return get_session()


# =============================================================================
# TASK TOOL FACTORY (SOLID — injected ITaskRepository)
# =============================================================================


def build_task_tools(task_repo: ITaskRepository) -> list[Tool]:
    """
    Factory: creates Task tools with a pre-injected repository.

    This avoids direct DB access inside tool functions, making them unit-testable.
    """

    async def add_task(
        task_content: str | None = None, content: str | None = None, **kwargs: Any
    ) -> str:
        text = task_content or content or kwargs.get("text")
        if not text:
            return "Error: No task content provided."
        try:
            from src.core.domain.models import Task

            created = await task_repo.create(Task(content=text))
            return f"Task added: '{text}' (ID: {created.id})"
        except Exception as e:
            logger.exception("add_task failed: %s", e)
            return f"Error adding task: {e}"

    async def list_tasks(status_filter: str | None = None, **kwargs: Any) -> str:
        try:
            if status_filter and status_filter.lower() == "completed":
                tasks = await task_repo.get_completed()
            elif status_filter and status_filter.lower() == "pending":
                tasks = await task_repo.get_pending()
            else:
                tasks = await task_repo.get_all(limit=20)
            if not tasks:
                return "No tasks found."
            lines = [f"Tasks ({len(tasks)}):"]
            for t in tasks:
                icon = "✅" if t.status.value == "completed" else "⬜"
                lines.append(f"  {icon} [{t.id}] {t.content}")
            return "\n".join(lines)
        except Exception as e:
            logger.exception("list_tasks failed: %s", e)
            return f"Error listing tasks: {e}"

    async def complete_task(
        identifier: str | None = None, task_id: str | None = None, **kwargs: Any
    ) -> str:
        target = identifier or task_id or kwargs.get("id")
        if not target:
            return "Error: No task identifier provided."
        try:
            if str(target).isdigit():
                updated = await task_repo.mark_complete(int(target))
                if updated:
                    return f"✅ Task '{updated.content}' marked as completed."
                return f"Task ID {target} not found."
            # Fallback: find by content
            tasks = await task_repo.get_all()
            match = next((t for t in tasks if target.lower() in t.content.lower()), None)
            if match and match.id is not None:
                updated = await task_repo.mark_complete(match.id)
                if updated:
                    return f"✅ Task '{updated.content}' marked as completed."
                return f"Task '{target}' could not be completed."
            return f"Task '{target}' not found."
        except Exception as e:
            logger.exception("complete_task failed: %s", e)
            return f"Error completing task: {e}"

    async def get_task_summary(**kwargs: Any) -> str:
        try:
            summary = await task_repo.get_summary()
            if summary["total"] == 0:
                return "You have no tasks."
            return (
                f"📋 Tasks: {summary['total']} total "
                f"({summary['pending']} pending, {summary['completed']} completed)"
            )
        except Exception as e:
            logger.exception("get_task_summary failed: %s", e)
            return f"Error getting summary: {e}"

    return [
        Tool(
            name="add_task",
            description=(
                "Creates a new task/todo item and saves it to the database. "
                "Trigger: 'add task buy groceries', 'create todo', 'new task', 'remind me to'"
            ),
            category=ToolCategory.TASK_MANAGER,
            function=add_task,
            parameters={"task_content": {"type": "string", "description": "Task description"}},
        ),
        Tool(
            name="list_tasks",
            description=(
                "Lists all tasks from the database. Can filter by status: 'pending', 'completed', or 'all'. "
                "Defaults to showing all tasks. "
                "Trigger: 'show my tasks', 'list todos', 'pending tasks', 'what do I need to do'"
            ),
            category=ToolCategory.TASK_MANAGER,
            function=list_tasks,
            parameters={
                "status_filter": {
                    "type": "string",
                    "description": "Filter: pending, completed, or all",
                }
            },
        ),
        Tool(
            name="complete_task",
            description=(
                "Marks a task as completed by ID or partial content match. "
                "Trigger: 'complete task buy groceries', 'mark task done', 'finish task 3', 'I did the laundry'"
            ),
            category=ToolCategory.TASK_MANAGER,
            function=complete_task,
            parameters={
                "identifier": {"type": "string", "description": "Task ID or partial content"}
            },
        ),
        Tool(
            name="get_task_summary",
            description=(
                "Returns a summary of task statistics: total count, pending count, and completed count. "
                "Trigger: 'task summary', 'how many tasks', 'task stats', 'productivity report'"
            ),
            category=ToolCategory.TASK_MANAGER,
            function=get_task_summary,
        ),
    ]


# =============================================================================
# POMODORO TOOL FACTORY (SOLID — injected IPomodoroRepository)
# =============================================================================


def build_pomodoro_tools(pomodoro_repo: IPomodoroRepository) -> list[Tool]:
    """
    Factory: creates Pomodoro tools wired to the persistence layer.
    """

    async def start_pomodoro(task: str = "Focus session", duration: int = 25, **kwargs: Any) -> str:
        """Start a new Pomodoro timer session."""
        # Prevent double-starting if one is already active
        active = await pomodoro_repo.get_active()
        if active:
            return (
                f"⏱️ A Pomodoro is already running ({active.state.value}, "
                f"task: '{active.task_description}'). Stop it first."
            )
        session = await pomodoro_repo.create(
            PomodoroSession(
                state=PomodoroState.WORKING,
                task_description=task,
                work_duration_minutes=duration,
                started_at=datetime.now(UTC),
            )
        )
        return (
            f"🍅 Pomodoro started! Task: '{task}' | Duration: {duration} min | ID: {session.id}\n"
            f"Stay focused — I'll remind you when it's done."
        )

    async def stop_pomodoro(**kwargs: Any) -> str:
        """Stop/cancel the current Pomodoro session."""
        active = await pomodoro_repo.get_active()
        if not active:
            return "No active Pomodoro session to stop."
        if active.id is None:
            return "Active Pomodoro has no ID — cannot stop it."
        updated = await pomodoro_repo.update_state(active.id, PomodoroState.COMPLETED)
        if updated:
            return (
                f"Pomodoro session stopped (ID: {updated.id}, task: '{updated.task_description}')"
            )
        return "Could not stop the Pomodoro session."

    async def pomodoro_status(**kwargs: Any) -> str:
        """Get the status of the current Pomodoro session."""
        active = await pomodoro_repo.get_active()
        if not active:
            completed_today = await pomodoro_repo.count_completed_today()
            return f"No active Pomodoro. Cycles completed today: {completed_today} 🍅"

        elapsed = ""
        if active.started_at:
            diff = datetime.now(UTC) - active.started_at.replace(tzinfo=UTC)
            mins = int(diff.total_seconds() // 60)
            elapsed = f" | Elapsed: {mins} min"

        return (
            f"🍅 Pomodoro: {active.state.value.upper()}\n"
            f"Task: '{active.task_description}'{elapsed}\n"
            f"Cycles completed: {active.cycles_completed}"
        )

    return [
        Tool(
            name="start_pomodoro",
            description="Start a Pomodoro timer (25 min focus). Trigger: 'start pomodoro', 'pomodoro', 'focus timer'",
            category=ToolCategory.TASK_MANAGER,
            function=start_pomodoro,
            parameters={
                "task": {"type": "string", "description": "What you're working on"},
                "duration": {
                    "type": "integer",
                    "description": "Work duration in minutes (default 25)",
                },
            },
        ),
        Tool(
            name="stop_pomodoro",
            description="Stop the current Pomodoro session. Trigger: 'stop pomodoro', 'cancel timer'",
            category=ToolCategory.TASK_MANAGER,
            function=stop_pomodoro,
        ),
        Tool(
            name="pomodoro_status",
            description="Check Pomodoro session status. Trigger: 'pomodoro status', 'how much time left'",
            category=ToolCategory.TASK_MANAGER,
            function=pomodoro_status,
        ),
    ]


# =============================================================================
# NOTE / REMINDER TOOL FACTORIES (SOLID — injected repositories)
# =============================================================================


def build_note_tools(note_repo: INoteRepository) -> list[Tool]:
    """Factory: creates note tools with an injected repository."""

    async def create_note(
        title: str | None = None, content: str | None = None, **kwargs: Any
    ) -> str:
        note_title = title or kwargs.get("name") or "Untitled Note"
        note_content = content or kwargs.get("text") or ""
        try:
            created = await note_repo.create(Note(title=note_title, content=note_content))
            return f"📝 Note created: '{note_title}' (ID: {created.id})"
        except Exception as e:
            logger.exception("create_note failed: %s", e)
            return f"Error creating note: {e}"

    async def list_notes(**kwargs: Any) -> str:
        try:
            notes = await note_repo.get_recent(limit=15)
            if not notes:
                return "No notes found."
            lines = [f"Notes ({len(notes)}):"]
            for n in notes:
                date_str = n.created_at.strftime("%m/%d") if n.created_at else ""
                lines.append(f"  📝 [{n.id}] {n.title} ({date_str})")
            return "\n".join(lines)
        except Exception as e:
            logger.exception("list_notes failed: %s", e)
            return f"Error listing notes: {e}"

    async def get_note(identifier: str | None = None, **kwargs: Any) -> str:
        target = identifier or kwargs.get("id") or kwargs.get("title")
        if not target:
            return "Error: No note identifier provided."
        try:
            note = None
            if str(target).isdigit():
                note = await note_repo.get_by_id(int(target))
            if not note:
                matches = await note_repo.search(str(target))
                note = matches[0] if matches else None
            if not note:
                return f"Note '{target}' not found."
            return f"📝 {note.title}\n{'─' * 30}\n{note.content}"
        except Exception as e:
            logger.exception("get_note failed: %s", e)
            return f"Error getting note: {e}"

    return [
        Tool(
            name="create_note",
            description="Create a new note. Trigger: 'create note', 'take note', 'new note'",
            category=ToolCategory.TASK_MANAGER,
            function=create_note,
            parameters={
                "title": {"type": "string", "description": "Note title"},
                "content": {"type": "string", "description": "Note content"},
            },
        ),
        Tool(
            name="list_notes",
            description="List all notes. Trigger: 'show notes', 'my notes'",
            category=ToolCategory.TASK_MANAGER,
            function=list_notes,
        ),
        Tool(
            name="get_note",
            description="Get a specific note by ID or title. Trigger: 'read note', 'show note'",
            category=ToolCategory.TASK_MANAGER,
            function=get_note,
            parameters={"identifier": {"type": "string", "description": "Note ID or title"}},
        ),
    ]


def build_reminder_tools(reminder_repo: IReminderRepository) -> list[Tool]:
    """Factory: creates reminder tools with an injected repository."""

    async def add_reminder(
        title: str | None = None, time: str | None = None, **kwargs: Any
    ) -> str:
        reminder_title = title or kwargs.get("text") or kwargs.get("message")
        reminder_time = time or kwargs.get("when") or kwargs.get("at")
        if not reminder_title:
            return "Error: No reminder title provided."
        try:
            from dateparser import parse as parse_date

            parsed_time = parse_date(reminder_time) if reminder_time else None
        except ImportError:
            parsed_time = None
        parsed_time = parsed_time or datetime.now(UTC)

        try:
            created = await reminder_repo.create(
                Reminder(title=reminder_title, time=parsed_time)
            )
            time_str = created.time.strftime("%Y-%m-%d %H:%M")
            return f"⏰ Reminder set: '{reminder_title}' at {time_str}"
        except Exception as e:
            logger.exception("add_reminder failed: %s", e)
            return f"Error adding reminder: {e}"

    async def list_reminders(**kwargs: Any) -> str:
        try:
            reminders = await reminder_repo.get_active()
            if not reminders:
                return "No active reminders."
            lines = [f"⏰ Reminders ({len(reminders)}):"]
            for r in reminders[:10]:
                time_str = r.time.strftime("%m/%d %H:%M") if r.time else "?"
                lines.append(f"  [{r.id}] {r.title} - {time_str}")
            return "\n".join(lines)
        except Exception as e:
            logger.exception("list_reminders failed: %s", e)
            return f"Error listing reminders: {e}"

    return [
        Tool(
            name="add_reminder",
            description="Create a reminder. Trigger: 'remind me', 'set reminder'",
            category=ToolCategory.TASK_MANAGER,
            function=add_reminder,
            parameters={
                "title": {"type": "string", "description": "Reminder title"},
                "time": {
                    "type": "string",
                    "description": "When (e.g. 'in 1 hour', 'tomorrow 9am')",
                },
            },
        ),
        Tool(
            name="list_reminders",
            description="List all reminders. Trigger: 'show reminders', 'my reminders'",
            category=ToolCategory.TASK_MANAGER,
            function=list_reminders,
        ),
    ]


# =============================================================================
# LEGACY BARE TOOLS (kept until container.py is fully migrated)
# These use _get_session() directly and will be removed in Phase 4.
# =============================================================================

from sqlalchemy import select


@tool(
    name="create_note",
    description="Create a new note. Trigger: 'create note', 'take note', 'new note'",
    category=ToolCategory.TASK_MANAGER,
    parameters={
        "title": {"type": "string", "description": "Note title"},
        "content": {"type": "string", "description": "Note content"},
    },
)
async def create_note(title: str | None = None, content: str | None = None, **kwargs: Any) -> str:
    note_title = title or kwargs.get("name") or "Untitled Note"
    note_content = content or kwargs.get("text") or ""
    try:
        async with _get_session() as db:
            from src.infra.persistence.orm_models import NoteORM

            note = NoteORM(title=note_title, content=note_content)
            db.add(note)
            await db.commit()
            await db.refresh(note)
            return f"📝 Note created: '{note_title}' (ID: {note.id})"
    except Exception as e:
        logger.exception("create_note failed: %s", e)
        return f"Error creating note: {e}"


@tool(
    name="list_notes",
    description="List all notes. Trigger: 'show notes', 'my notes'",
    category=ToolCategory.TASK_MANAGER,
)
async def list_notes(**kwargs: Any) -> str:
    try:
        async with _get_session() as db:
            from src.infra.persistence.orm_models import NoteORM

            stmt = select(NoteORM.id, NoteORM.title, NoteORM.created_at).order_by(
                NoteORM.created_at.desc()
            )
            result = await db.execute(stmt)
            notes = result.all()
            if not notes:
                return "No notes found."
            lines = [f"Notes ({len(notes)}):"]
            for n in notes[:15]:
                date_str = n.created_at.strftime("%m/%d") if n.created_at else ""
                lines.append(f"  📝 [{n.id}] {n.title} ({date_str})")
            if len(notes) > 15:
                lines.append(f"  ... and {len(notes) - 15} more")
            return "\n".join(lines)
    except Exception as e:
        logger.exception("list_notes failed: %s", e)
        return f"Error listing notes: {e}"


@tool(
    name="get_note",
    description="Get a specific note by ID or title. Trigger: 'read note', 'show note'",
    category=ToolCategory.TASK_MANAGER,
    parameters={"identifier": {"type": "string", "description": "Note ID or title"}},
)
async def get_note(identifier: str | None = None, **kwargs: Any) -> str:
    target = identifier or kwargs.get("id") or kwargs.get("title")
    if not target:
        return "Error: No note identifier provided."
    try:
        async with _get_session() as db:
            from src.infra.persistence.orm_models import NoteORM

            note = None
            if str(target).isdigit():
                result = await db.execute(select(NoteORM).where(NoteORM.id == int(target)))
                note = result.scalars().first()
            if not note:
                result = await db.execute(select(NoteORM).where(NoteORM.title.ilike(f"%{target}%")))
                note = result.scalars().first()
            if not note:
                return f"Note '{target}' not found."
            return f"📝 {note.title}\n{'─' * 30}\n{note.content}"
    except Exception as e:
        logger.exception("get_note failed: %s", e)
        return f"Error getting note: {e}"


@tool(
    name="add_reminder",
    description="Create a reminder. Trigger: 'remind me', 'set reminder'",
    category=ToolCategory.TASK_MANAGER,
    parameters={
        "title": {"type": "string", "description": "Reminder title"},
        "time": {"type": "string", "description": "When (e.g. 'in 1 hour', 'tomorrow 9am')"},
    },
)
async def add_reminder(title: str | None = None, time: str | None = None, **kwargs: Any) -> str:
    reminder_title = title or kwargs.get("text") or kwargs.get("message")
    reminder_time = time or kwargs.get("when") or kwargs.get("at")
    if not reminder_title:
        return "Error: No reminder title provided."
    try:
        from dateparser import parse as parse_date

        parsed_time = parse_date(reminder_time) if reminder_time else None
    except ImportError:
        parsed_time = None
    parsed_time = parsed_time or datetime.now(UTC)

    try:
        async with _get_session() as db:
            from src.infra.persistence.orm_models import ReminderORM

            reminder = ReminderORM(title=reminder_title, time=parsed_time)
            db.add(reminder)
            await db.commit()
            await db.refresh(reminder)
            time_str = parsed_time.strftime("%Y-%m-%d %H:%M")
            return f"⏰ Reminder set: '{reminder_title}' at {time_str}"
    except Exception as e:
        logger.exception("add_reminder failed: %s", e)
        return f"Error adding reminder: {e}"


@tool(
    name="list_reminders",
    description="List all reminders. Trigger: 'show reminders', 'my reminders'",
    category=ToolCategory.TASK_MANAGER,
)
async def list_reminders(**kwargs: Any) -> str:
    try:
        async with _get_session() as db:
            from src.infra.persistence.orm_models import ReminderORM

            stmt = (
                select(ReminderORM.id, ReminderORM.title, ReminderORM.time, ReminderORM.status)
                .where(ReminderORM.status == "active")
                .order_by(ReminderORM.time.asc())
            )
            result = await db.execute(stmt)
            reminders = result.all()
            if not reminders:
                return "No active reminders."
            lines = [f"⏰ Reminders ({len(reminders)}):"]
            for r in reminders[:10]:
                time_str = r.time.strftime("%m/%d %H:%M") if r.time else "?"
                lines.append(f"  [{r.id}] {r.title} - {time_str}")
            return "\n".join(lines)
    except Exception as e:
        logger.exception("list_reminders failed: %s", e)
        return f"Error listing reminders: {e}"


# =============================================================================
# TOOL COLLECTION
# =============================================================================


def get_productivity_tools() -> list[Tool]:
    """Get legacy (session-injected) productivity tools."""
    return [
        create_note._tool_metadata,  # type: ignore[attr-defined]
        list_notes._tool_metadata,  # type: ignore[attr-defined]
        get_note._tool_metadata,  # type: ignore[attr-defined]
        add_reminder._tool_metadata,  # type: ignore[attr-defined]
        list_reminders._tool_metadata,  # type: ignore[attr-defined]
    ]
