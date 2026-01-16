"""
Productivity tools for Amadeus AI Assistant.

Includes tasks, notes, and reminders management.
Migrated from task_utils.py, note_utils.py, reminder_utils.py to Clean Architecture.

Note: These tools interact with the database via the repository layer.
For now, they use direct async session calls (legacy compatibility).
Future: Inject repositories via DI container.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import case, delete, func, select, update

from src.infra.tools.base import Tool, ToolCategory, tool


logger = logging.getLogger(__name__)


# =============================================================================
# DATABASE SESSION HELPER
# =============================================================================

def _get_session():
    """Get async session - imported lazily to avoid circular imports."""
    from src.infra.persistence.database import get_session
    return get_session()


def _get_task_model():
    """Get Task ORM model - imported lazily."""
    from src.infra.persistence.orm_models import TaskORM
    return TaskORM


def _get_note_model():
    """Get Note ORM model - imported lazily."""
    from src.infra.persistence.orm_models import NoteORM
    return NoteORM


def _get_reminder_model():
    """Get Reminder ORM model - imported lazily."""
    from src.infra.persistence.orm_models import ReminderORM
    return ReminderORM


# =============================================================================
# TASK TOOLS
# =============================================================================

@tool(
    name="add_task",
    description="Create a new task. Trigger: 'add task', 'create task', 'new todo'",
    category=ToolCategory.PRODUCTIVITY,
    parameters={"task_content": {"type": "string", "description": "Task description"}}
)
async def add_task(task_content: str | None = None, content: str | None = None, **kwargs: Any) -> str:
    """Add a new task to the database."""
    task_text = task_content or content or kwargs.get("text")
    if not task_text:
        return "Error: No task content provided."
    
    try:
        async with _get_session() as db:
            TaskORM = _get_task_model()
            task = TaskORM(content=task_text)
            db.add(task)
            await db.commit()
            await db.refresh(task)
            return f"Task added: '{task_text}' (ID: {task.id})"
    except Exception as e:
        logger.error(f"Error adding task: {e}")
        return f"Error adding task: {e}"


@tool(
    name="list_tasks",
    description="List all tasks. Trigger: 'show tasks', 'my todos', 'list tasks'",
    category=ToolCategory.PRODUCTIVITY,
    parameters={"status_filter": {"type": "string", "description": "Filter: pending, completed, or all"}}
)
async def list_tasks(status_filter: str | None = None, **kwargs: Any) -> str:
    """List all tasks with optional status filter."""
    try:
        async with _get_session() as db:
            TaskORM = _get_task_model()
            stmt = select(TaskORM.id, TaskORM.content, TaskORM.status)
            
            if status_filter and status_filter != "all":
                stmt = stmt.where(TaskORM.status == status_filter)
            
            stmt = stmt.order_by(TaskORM.created_at.desc())
            result = await db.execute(stmt)
            tasks = result.all()
            
            if not tasks:
                return "No tasks found."
            
            lines = [f"Tasks ({len(tasks)}):"]
            for t in tasks[:20]:  # Limit display
                status_icon = "✅" if t.status == "completed" else "⬜"
                lines.append(f"  {status_icon} [{t.id}] {t.content}")
            
            if len(tasks) > 20:
                lines.append(f"  ... and {len(tasks) - 20} more")
            
            return "\n".join(lines)
            
    except Exception as e:
        logger.error(f"Error listing tasks: {e}")
        return f"Error listing tasks: {e}"


@tool(
    name="complete_task",
    description="Mark a task as complete. Trigger: 'complete task', 'finish task', 'done with'",
    category=ToolCategory.PRODUCTIVITY,
    parameters={"identifier": {"type": "string", "description": "Task ID or partial content"}}
)
async def complete_task(identifier: str | None = None, task_id: str | None = None, **kwargs: Any) -> str:
    """Mark a task as completed."""
    target = identifier or task_id or kwargs.get("id") or kwargs.get("name")
    if not target:
        return "Error: No task identifier provided."
    
    try:
        async with _get_session() as db:
            TaskORM = _get_task_model()
            task = None
            
            # Try by ID first
            if target.isdigit():
                stmt = select(TaskORM).where(TaskORM.id == int(target))
                result = await db.execute(stmt)
                task = result.scalars().first()
            
            # Try by content match
            if not task:
                stmt = select(TaskORM).where(TaskORM.content.ilike(f"%{target}%"))
                result = await db.execute(stmt)
                task = result.scalars().first()
            
            if not task:
                return f"Task '{target}' not found."
            
            if task.status == "completed":
                return f"Task '{task.content}' is already completed."
            
            await db.execute(
                update(TaskORM)
                .where(TaskORM.id == task.id)
                .values(status="completed", completed_at=datetime.now(timezone.utc))
            )
            await db.commit()
            return f"✅ Task '{task.content}' marked as completed."
            
    except Exception as e:
        logger.error(f"Error completing task: {e}")
        return f"Error completing task: {e}"


@tool(
    name="delete_task",
    description="Delete a task. Trigger: 'delete task', 'remove task'",
    category=ToolCategory.PRODUCTIVITY,
    parameters={"identifier": {"type": "string", "description": "Task ID or partial content"}},
    requires_confirmation=True,
)
async def delete_task(identifier: str | None = None, task_id: str | None = None, **kwargs: Any) -> str:
    """Delete a task from the database."""
    target = identifier or task_id or kwargs.get("id")
    if not target:
        return "Error: No task identifier provided."
    
    try:
        async with _get_session() as db:
            TaskORM = _get_task_model()
            task = None
            
            if target.isdigit():
                stmt = select(TaskORM).where(TaskORM.id == int(target))
                result = await db.execute(stmt)
                task = result.scalars().first()
            
            if not task:
                stmt = select(TaskORM).where(TaskORM.content.ilike(f"%{target}%"))
                result = await db.execute(stmt)
                task = result.scalars().first()
            
            if not task:
                return f"Task '{target}' not found."
            
            task_content = task.content
            await db.execute(delete(TaskORM).where(TaskORM.id == task.id))
            await db.commit()
            return f"🗑️ Task '{task_content}' deleted."
            
    except Exception as e:
        logger.error(f"Error deleting task: {e}")
        return f"Error deleting task: {e}"


@tool(
    name="get_task_summary",
    description="Get task statistics. Trigger: 'task summary', 'how many tasks'",
    category=ToolCategory.PRODUCTIVITY,
)
async def get_task_summary() -> str:
    """Get a summary of all tasks."""
    try:
        async with _get_session() as db:
            TaskORM = _get_task_model()
            stmt = select(
                func.count(TaskORM.id).label("total"),
                func.sum(case((TaskORM.status == "completed", 1), else_=0)).label("completed")
            )
            result = await db.execute(stmt)
            row = result.first()
            
            total = row.total or 0
            completed = row.completed or 0
            pending = total - completed
            
            if total == 0:
                return "You have no tasks."
            
            return f"📋 Tasks: {total} total ({pending} pending, {completed} completed)"
            
    except Exception as e:
        logger.error(f"Error getting task summary: {e}")
        return f"Error getting summary: {e}"


# =============================================================================
# NOTE TOOLS
# =============================================================================

@tool(
    name="create_note",
    description="Create a new note. Trigger: 'create note', 'take note', 'new note'",
    category=ToolCategory.PRODUCTIVITY,
    parameters={
        "title": {"type": "string", "description": "Note title"},
        "content": {"type": "string", "description": "Note content"}
    }
)
async def create_note(title: str | None = None, content: str | None = None, **kwargs: Any) -> str:
    """Create a new note."""
    note_title = title or kwargs.get("name") or "Untitled Note"
    note_content = content or kwargs.get("text") or ""
    
    try:
        async with _get_session() as db:
            NoteORM = _get_note_model()
            note = NoteORM(title=note_title, content=note_content)
            db.add(note)
            await db.commit()
            await db.refresh(note)
            return f"📝 Note created: '{note_title}' (ID: {note.id})"
            
    except Exception as e:
        logger.error(f"Error creating note: {e}")
        return f"Error creating note: {e}"


@tool(
    name="list_notes",
    description="List all notes. Trigger: 'show notes', 'my notes'",
    category=ToolCategory.PRODUCTIVITY,
)
async def list_notes(**kwargs: Any) -> str:
    """List all notes."""
    try:
        async with _get_session() as db:
            NoteORM = _get_note_model()
            stmt = select(NoteORM.id, NoteORM.title, NoteORM.created_at).order_by(NoteORM.created_at.desc())
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
        logger.error(f"Error listing notes: {e}")
        return f"Error listing notes: {e}"


@tool(
    name="get_note",
    description="Get a specific note by ID or title. Trigger: 'read note', 'show note'",
    category=ToolCategory.PRODUCTIVITY,
    parameters={"identifier": {"type": "string", "description": "Note ID or title"}}
)
async def get_note(identifier: str | None = None, note_id: str | None = None, **kwargs: Any) -> str:
    """Get a note's content."""
    target = identifier or note_id or kwargs.get("id") or kwargs.get("title")
    if not target:
        return "Error: No note identifier provided."
    
    try:
        async with _get_session() as db:
            NoteORM = _get_note_model()
            note = None
            
            if target.isdigit():
                stmt = select(NoteORM).where(NoteORM.id == int(target))
                result = await db.execute(stmt)
                note = result.scalars().first()
            
            if not note:
                stmt = select(NoteORM).where(NoteORM.title.ilike(f"%{target}%"))
                result = await db.execute(stmt)
                note = result.scalars().first()
            
            if not note:
                return f"Note '{target}' not found."
            
            return f"📝 {note.title}\n{'─' * 30}\n{note.content}"
            
    except Exception as e:
        logger.error(f"Error getting note: {e}")
        return f"Error getting note: {e}"


@tool(
    name="delete_note",
    description="Delete a note. Trigger: 'delete note'",
    category=ToolCategory.PRODUCTIVITY,
    parameters={"identifier": {"type": "string", "description": "Note ID or title"}},
    requires_confirmation=True,
)
async def delete_note(identifier: str | None = None, **kwargs: Any) -> str:
    """Delete a note."""
    target = identifier or kwargs.get("id") or kwargs.get("title")
    if not target:
        return "Error: No note identifier provided."
    
    try:
        async with _get_session() as db:
            NoteORM = _get_note_model()
            note = None
            
            if target.isdigit():
                stmt = select(NoteORM).where(NoteORM.id == int(target))
                result = await db.execute(stmt)
                note = result.scalars().first()
            
            if not note:
                stmt = select(NoteORM).where(NoteORM.title.ilike(f"%{target}%"))
                result = await db.execute(stmt)
                note = result.scalars().first()
            
            if not note:
                return f"Note '{target}' not found."
            
            note_title = note.title
            await db.execute(delete(NoteORM).where(NoteORM.id == note.id))
            await db.commit()
            return f"🗑️ Note '{note_title}' deleted."
            
    except Exception as e:
        logger.error(f"Error deleting note: {e}")
        return f"Error deleting note: {e}"


# =============================================================================
# REMINDER TOOLS
# =============================================================================

@tool(
    name="add_reminder",
    description="Create a reminder. Trigger: 'remind me', 'set reminder'",
    category=ToolCategory.PRODUCTIVITY,
    parameters={
        "title": {"type": "string", "description": "Reminder title"},
        "time": {"type": "string", "description": "When to remind (e.g., 'in 1 hour', 'tomorrow 9am')"}
    }
)
async def add_reminder(title: str | None = None, time: str | None = None, **kwargs: Any) -> str:
    """Add a new reminder."""
    reminder_title = title or kwargs.get("text") or kwargs.get("message")
    reminder_time = time or kwargs.get("when") or kwargs.get("at")
    
    if not reminder_title:
        return "Error: No reminder title provided."
    
    # Parse time (simplified - in production use dateparser)
    try:
        from dateparser import parse as parse_date
        parsed_time = parse_date(reminder_time) if reminder_time else datetime.now(timezone.utc)
        if not parsed_time:
            parsed_time = datetime.now(timezone.utc)
    except ImportError:
        parsed_time = datetime.now(timezone.utc)
    
    try:
        async with _get_session() as db:
            ReminderORM = _get_reminder_model()
            reminder = ReminderORM(title=reminder_title, time=parsed_time)
            db.add(reminder)
            await db.commit()
            await db.refresh(reminder)
            
            time_str = parsed_time.strftime("%Y-%m-%d %H:%M")
            return f"⏰ Reminder set: '{reminder_title}' at {time_str}"
            
    except Exception as e:
        logger.error(f"Error adding reminder: {e}")
        return f"Error adding reminder: {e}"


@tool(
    name="list_reminders",
    description="List all reminders. Trigger: 'show reminders', 'my reminders'",
    category=ToolCategory.PRODUCTIVITY,
)
async def list_reminders(**kwargs: Any) -> str:
    """List all active reminders."""
    try:
        async with _get_session() as db:
            ReminderORM = _get_reminder_model()
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
        logger.error(f"Error listing reminders: {e}")
        return f"Error listing reminders: {e}"


@tool(
    name="delete_reminder",
    description="Delete a reminder. Trigger: 'delete reminder', 'cancel reminder'",
    category=ToolCategory.PRODUCTIVITY,
    parameters={"identifier": {"type": "string", "description": "Reminder ID or title"}},
    requires_confirmation=True,
)
async def delete_reminder(identifier: str | None = None, **kwargs: Any) -> str:
    """Delete a reminder."""
    target = identifier or kwargs.get("id") or kwargs.get("title")
    if not target:
        return "Error: No reminder identifier provided."
    
    try:
        async with _get_session() as db:
            ReminderORM = _get_reminder_model()
            reminder = None
            
            if target.isdigit():
                stmt = select(ReminderORM).where(ReminderORM.id == int(target))
                result = await db.execute(stmt)
                reminder = result.scalars().first()
            
            if not reminder:
                stmt = select(ReminderORM).where(ReminderORM.title.ilike(f"%{target}%"))
                result = await db.execute(stmt)
                reminder = result.scalars().first()
            
            if not reminder:
                return f"Reminder '{target}' not found."
            
            reminder_title = reminder.title
            await db.execute(delete(ReminderORM).where(ReminderORM.id == reminder.id))
            await db.commit()
            return f"🗑️ Reminder '{reminder_title}' deleted."
            
    except Exception as e:
        logger.error(f"Error deleting reminder: {e}")
        return f"Error deleting reminder: {e}"


# =============================================================================
# TOOL COLLECTION
# =============================================================================

def get_productivity_tools() -> list[Tool]:
    """Get all productivity tools for manual registration."""
    tools = []
    for name, obj in globals().items():
        if hasattr(obj, "_tool_metadata"):
            tools.append(obj._tool_metadata)
    return tools
