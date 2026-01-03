# reminder_utils.py

from typing import Dict, List, Optional
from db import get_async_session, init_db_async
import models
from datetime import datetime, timezone
import dateparser
# Lazy import of speak to avoid requiring faster_whisper for tests
# import speak  # Will be imported inside function when needed
import asyncio
import time
from typing import cast
from sqlalchemy import select, update, delete

# Try to use zoneinfo (Python 3.9+), fall back to pytz
try:
    from zoneinfo import ZoneInfo
    HAS_ZONEINFO = True
except ImportError:
    try:
        import pytz
        HAS_ZONEINFO = False
    except ImportError:
        # No timezone support available
        HAS_ZONEINFO = None
        pytz = None

def get_timezone(tz_name: Optional[str] = None):
    """Get timezone object, using zoneinfo if available, otherwise pytz."""
    if tz_name is None:
        import config
        tz_name = config.TIMEZONE
    
    if HAS_ZONEINFO:
        return ZoneInfo(tz_name)
    elif pytz:
        return pytz.timezone(tz_name)
    else:
        # Fallback to UTC if no timezone library available
        return timezone.utc


# Async reminder functions. Call await init_db_async() at startup.


async def add_reminder(title: str, time_str: str, description: str = "") -> Dict:
    parsed = dateparser.parse(time_str)
    if not parsed:
        return {"status": "error", "message": "Invalid date/time provided."}
    
    # Ensure timezone-aware datetime
    if parsed.tzinfo is None:
        # If no timezone info, assume local timezone from config
        local_tz = get_timezone()
        if HAS_ZONEINFO:
            parsed = parsed.replace(tzinfo=local_tz)
        elif pytz:
            parsed = local_tz.localize(parsed)
        else:
            # Fallback: use UTC
            parsed = parsed.replace(tzinfo=timezone.utc)
    
    # Compare with timezone-aware current time
    now = datetime.now(parsed.tzinfo)
    if parsed < now:
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


# Legacy loop removed. Logic moved to clock_service.py



# Background monitoring is now handled by ClockService in a separate process.
# This file only contains CRUD operations used by the main application.
