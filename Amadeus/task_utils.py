# task_utils.py

from typing import Optional, List, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from db import async_session, init_db_async, get_async_session
import models
from datetime import datetime, timezone
from sqlalchemy import select, update, delete, func


# Ensure DB initialized asynchronously; caller (api) should call init_db_async on startup


async def add_task(task_content: str) -> Dict:
    async with get_async_session() as db:
        task = models.Task(content=task_content)
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return {"id": task.id, "content": task.content, "status": task.status}


async def list_tasks(status_filter: Optional[str] = None) -> List[Dict]:
    """List tasks with optimized query using indexes."""
    async with get_async_session() as db:
        # Use indexed columns for better performance
        stmt = select(
            models.Task.id,
            models.Task.content,
            models.Task.status,
            models.Task.created_at,
            models.Task.completed_at
        )
        if status_filter:
            # Use indexed status column
            stmt = stmt.where(models.Task.status == status_filter)
        # Use indexed created_at for sorting
        stmt = stmt.order_by(models.Task.created_at.desc())
        
        res = await db.execute(stmt)
        tasks = res.all()
        
        # Convert to dict format efficiently
        result = [
            {
                "id": task.id,
                "content": task.content,
                "status": task.status,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            }
            for task in tasks
        ]
        return result


async def complete_task(identifier: str) -> str:
    async with get_async_session() as db:
        task = None
        if identifier.isdigit():
            stmt = select(models.Task).where(models.Task.id == int(identifier))
            res = await db.execute(stmt)
            task = res.scalars().first()
        if not task:
            stmt = select(models.Task).where(models.Task.content.ilike(f"%{identifier}%"))
            res = await db.execute(stmt)
            task = res.scalars().first()
        if not task:
            return f"Task '{identifier}' not found."
        current_status = getattr(task, 'status', None)
        if current_status == 'completed':
            return f"Task '{getattr(task, 'content', '')}' is already marked as completed."
        # Use timezone-aware datetime
        completed_at = datetime.now(timezone.utc)
        await db.execute(update(models.Task).where(models.Task.id == task.id).values(status='completed', completed_at=completed_at))
        await db.commit()
        return f"Task '{task.content}' marked as completed."


async def delete_task(identifier: str) -> str:
    async with get_async_session() as db:
        task = None
        if identifier.isdigit():
            stmt = select(models.Task).where(models.Task.id == int(identifier))
            res = await db.execute(stmt)
            task = res.scalars().first()
        if not task:
            stmt = select(models.Task).where(models.Task.content.ilike(f"%{identifier}%"))
            res = await db.execute(stmt)
            task = res.scalars().first()
        if not task:
            return f"Task '{identifier}' not found."
        await db.execute(delete(models.Task).where(models.Task.id == task.id))
        await db.commit()
        return f"Task '{task.content}' deleted successfully."


async def get_task_summary() -> str:
    """Get task summary with optimized query using single aggregation."""
    async with get_async_session() as db:
        # Optimized: Single query with conditional aggregation
        from sqlalchemy import case
        stmt = select(
            func.count(models.Task.id).label('total'),
            func.sum(case((models.Task.status == 'completed', 1), else_=0)).label('completed')
        )
        result = await db.execute(stmt)
        row = result.first()
        
        total = row.total or 0
        completed = row.completed or 0
        pending = total - completed
        
        if total == 0:
            return "You have no tasks."
        return f"You have {total} tasks: {pending} pending and {completed} completed."
