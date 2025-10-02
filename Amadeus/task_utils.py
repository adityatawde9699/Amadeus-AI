# task_utils.py

from typing import Optional, List, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from db import async_session, init_db_async, get_async_session
import models
from datetime import datetime
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
    async with get_async_session() as db:
        stmt = select(models.Task)
        if status_filter:
            stmt = stmt.where(models.Task.status == status_filter)
        stmt = stmt.order_by(models.Task.created_at.desc())
        res = await db.execute(stmt)
        tasks = res.scalars().all()
        result = []
        for t in tasks:
            created_at = getattr(t, 'created_at', None)
            completed_at = getattr(t, 'completed_at', None)
            result.append({
                "id": getattr(t, 'id', None),
                "content": getattr(t, 'content', None),
                "status": getattr(t, 'status', None),
                "created_at": created_at.isoformat() if created_at is not None else None,
                "completed_at": completed_at.isoformat() if completed_at is not None else None,
            })
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
        await db.execute(update(models.Task).where(models.Task.id == task.id).values(status='completed', completed_at=datetime.utcnow()))
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
    async with get_async_session() as db:
        total = (await db.execute(select(func.count()).select_from(models.Task))).scalar_one()
        if total == 0:
            return "You have no tasks."
        completed = (await db.execute(select(func.count()).select_from(models.Task).where(models.Task.status == 'completed'))).scalar_one()
        pending = total - completed
        return f"You have {total} tasks: {pending} pending and {completed} completed."
