# task_utils.py

from typing import Optional, List, Dict
from sqlalchemy.orm import Session
from db import SessionLocal, init_db
import models
from datetime import datetime


# Ensure DB is initialized when module is imported
init_db()


def _get_session() -> Session:
    return SessionLocal()


def add_task(task_content: str) -> Dict:
    """Adds a task to the database."""
    with _get_session() as db:
        task = models.Task(content=task_content)
        db.add(task)
        db.commit()
        db.refresh(task)
        return {"id": task.id, "content": task.content, "status": task.status}


def list_tasks(status_filter: Optional[str] = None) -> List[Dict]:
    with _get_session() as db:
        query = db.query(models.Task)
        if status_filter:
            query = query.filter(models.Task.status == status_filter)
        tasks = query.order_by(models.Task.created_at.desc()).all()
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


def complete_task(identifier: str) -> str:
    with _get_session() as db:
        task = None
        if identifier.isdigit():
            task = db.query(models.Task).get(int(identifier))
        if not task:
            task = db.query(models.Task).filter(models.Task.content.ilike(f"%{identifier}%")) .first()
        if not task:
            return f"Task '{identifier}' not found."
        current_status = getattr(task, 'status', None)
        if current_status == 'completed':
            return f"Task '{getattr(task, 'content', '')}' is already marked as completed."
        setattr(task, 'status', 'completed')
        setattr(task, 'completed_at', datetime.utcnow())
        db.add(task)
        db.commit()
        return f"Task '{task.content}' marked as completed."


def delete_task(identifier: str) -> str:
    with _get_session() as db:
        task = None
        if identifier.isdigit():
            task = db.query(models.Task).get(int(identifier))
        if not task:
            task = db.query(models.Task).filter(models.Task.content.ilike(f"%{identifier}%")).first()
        if not task:
            return f"Task '{identifier}' not found."
        content = task.content
        db.delete(task)
        db.commit()
        return f"Task '{content}' deleted successfully."


def get_task_summary() -> str:
    with _get_session() as db:
        total = db.query(models.Task).count()
        if total == 0:
            return "You have no tasks."
        completed = db.query(models.Task).filter(models.Task.status == 'completed').count()
        pending = total - completed
        return f"You have {total} tasks: {pending} pending and {completed} completed."
