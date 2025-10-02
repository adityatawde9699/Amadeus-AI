# reminder_utils.py

from typing import Dict, List, Optional
from db import get_async_session, init_db_async
import models
from datetime import datetime
import dateparser
from speech_utils import speak
import asyncio
from sqlalchemy import select, update, delete


# Async reminder functions. Call await init_db_async() at startup.


async def add_reminder(title: str, time_str: str, description: str = "") -> Dict:
    parsed = dateparser.parse(time_str)
    if not parsed:
        return {"status": "error", "message": "Invalid date/time provided."}
    if parsed < datetime.now():
        return {"status": "error", "message": "Cannot set reminder for a past time."}
    async with get_async_session() as db:
        reminder = models.Reminder(title=title, time=parsed.isoformat(), description=description)
        db.add(reminder)
        await db.commit()
        await db.refresh(reminder)
        return {"status": "success", "message": f"Reminder set for {title} at {parsed.isoformat()}", "id": reminder.id}


async def list_reminders() -> List[Dict]:
    async with get_async_session() as db:
        stmt = select(models.Reminder).where(models.Reminder.status == 'active').order_by(models.Reminder.created_at.desc())
        res = await db.execute(stmt)
        reminders = res.scalars().all()
        return [{"id": r.id, "title": r.title, "time": r.time, "description": r.description, "status": r.status} for r in reminders]


async def delete_reminder(reminder_id: int) -> Dict:
    async with get_async_session() as db:
        stmt = select(models.Reminder).where(models.Reminder.id == reminder_id)
        res = await db.execute(stmt)
        rem = res.scalars().first()
        if not rem:
            return {"status": "error", "message": "Reminder not found."}
        await db.execute(delete(models.Reminder).where(models.Reminder.id == reminder_id))
        await db.commit()
        return {"status": "success", "message": f"Reminder {reminder_id} deleted."}


async def check_due_reminders_loop(stop_event: Optional[asyncio.Event] = None):
    """Async loop that periodically checks for due reminders and speaks them."""
    while True:
        if stop_event and stop_event.is_set():
            break
        async with get_async_session() as db:
            now = datetime.utcnow()
            stmt = select(models.Reminder).where(models.Reminder.status == 'active')
            res = await db.execute(stmt)
            due = res.scalars().all()
            for r in due:
                try:
                    time_str = getattr(r, 'time', None)
                    if not time_str:
                        continue
                    reminder_time = datetime.fromisoformat(str(time_str))
                except Exception:
                    continue
                if now >= reminder_time:
                    message = f"Reminder: {getattr(r, 'title', '')}."
                    desc = getattr(r, 'description', None)
                    if desc:
                        message += f" Description: {desc}"
                    print("🔔", message)
                    try:
                        speak(message)
                    except Exception:
                        pass
                    await db.execute(update(models.Reminder).where(models.Reminder.id == r.id).values(status='completed'))
            await db.commit()
        await asyncio.sleep(30)

