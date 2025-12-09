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


async def check_due_reminders_loop(stop_event: Optional[asyncio.Event] = None):
    """Async loop that periodically checks for due reminders and speaks them."""
    import logging
    import config
    logger = logging.getLogger(__name__)
    
    # Use timezone from config
    local_tz = get_timezone()
    
    while True:
        if stop_event and stop_event.is_set():
            break
        async with get_async_session() as db:
            # Get current time in timezone-aware format
            if HAS_ZONEINFO or pytz:
                now = datetime.now(local_tz)
            else:
                now = datetime.now(timezone.utc)
            
            # Optimized query using indexed columns
            stmt = select(
                models.Reminder.id,
                models.Reminder.title,
                models.Reminder.time,
                models.Reminder.description,
                models.Reminder.status
            ).where(
                models.Reminder.status == 'active'  # Use indexed status column
            ).order_by(
                models.Reminder.created_at.desc()  # Use indexed created_at
            )
            res = await db.execute(stmt)
            due = res.all()
            for r in due:
                try:
                    time_str = getattr(r, 'time', None)
                    if not time_str:
                        continue
                    
                    # Parse reminder time - handle both timezone-aware and naive strings
                    reminder_time = datetime.fromisoformat(str(time_str))
                    
                    # If reminder_time is naive, assume it's in local timezone
                    if reminder_time.tzinfo is None:
                        if HAS_ZONEINFO:
                            reminder_time = reminder_time.replace(tzinfo=local_tz)
                        elif pytz:
                            reminder_time = local_tz.localize(reminder_time)
                        else:
                            reminder_time = reminder_time.replace(tzinfo=timezone.utc)
                    
                    # Normalize both to same timezone for comparison
                    if now.tzinfo != reminder_time.tzinfo:
                        reminder_time = reminder_time.astimezone(now.tzinfo)
                    
                except Exception as e:
                    logger.warning(f"Error parsing reminder time: {e}")
                    continue
                
                if now >= reminder_time:
                    message = f"Reminder: {getattr(r, 'title', '')}."
                    desc = getattr(r, 'description', None)
                    if desc:
                        message += f" Description: {desc}"
                    print("🔔", message)
                    try:
                        # Lazy import to avoid requiring faster_whisper for tests
                        from speech_utils import speak
                        speak(message)
                    except (ImportError, Exception):
                        # If speech_utils is not available (e.g., in tests), just print
                        pass
                    await db.execute(update(models.Reminder).where(models.Reminder.id == r.id).values(status='completed'))
            await db.commit()
        
        import config
        await asyncio.sleep(config.REMINDER_CHECK_INTERVAL)


class ReminderManager:
    """Compatibility wrapper that runs the async reminder loop in a background thread
    and exposes synchronous methods used by existing code (like `Amadeus`).
    """
    def __init__(self):
        # Types are initialized to None; wrapper will start a dedicated loop/thread
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = None
        self._stop_event: asyncio.Event | None = None

    def _ensure_loop_ready(self, timeout: Optional[float] = None) -> bool:
        """Wait (briefly) for the background thread to create the event loop.
        Returns True if loop was set, False on timeout.
        """
        if timeout is None:
            import config
            timeout = config.REMINDER_LOOP_STARTUP_TIMEOUT
        start = time.time()
        while time.time() - start < timeout:
            if self._loop is not None:
                return True
            time.sleep(0.05)
        return False

    def _start_loop_in_thread(self):
        import threading

        def _runner():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._stop_event = asyncio.Event()
            # Run the check loop until stop_event is set
            self._loop.run_until_complete(check_due_reminders_loop(self._stop_event))

        self._thread = threading.Thread(target=_runner, daemon=True)
        self._thread.start()

    def start_monitoring(self):
        if self._thread and self._thread.is_alive():
            return
        self._start_loop_in_thread()
        print("Reminder monitoring started (compat wrapper).")

    def stop_monitoring(self):
        if not self._loop or not self._thread or not self._stop_event:
            return
        # Signal the async stop_event from the thread's loop
        # Use a coroutine to set the asyncio.Event inside the thread's loop
        async def _set_event():
            evt = cast(asyncio.Event, self._stop_event)
            evt.set()
        import config
        loop = cast(asyncio.AbstractEventLoop, self._loop)
        fut = asyncio.run_coroutine_threadsafe(_set_event(), loop)
        try:
            fut.result(timeout=config.REMINDER_LOOP_STOP_TIMEOUT)
        except Exception:
            pass
        self._thread.join(timeout=config.REMINDER_LOOP_STOP_TIMEOUT)
        print("Reminder monitoring stopped (compat wrapper).")

    def add_reminder(self, title: str, time_str: str, description: str = ""):
        # Schedule the async add_reminder on the running loop
        if not self._loop:
            # start the loop if needed
            self.start_monitoring()
            if not self._ensure_loop_ready():
                return {"status": "error", "message": "Reminder system failed to start"}
        coro = add_reminder(title, time_str, description)
        loop = cast(asyncio.AbstractEventLoop, self._loop)
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return fut.result()

    def list_reminders(self):
        if not self._loop:
            return []
        coro = list_reminders()
        loop = cast(asyncio.AbstractEventLoop, self._loop)
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return fut.result()

    def delete_reminder(self, reminder_id: int):
        if not self._loop:
            return {"status": "error", "message": "Reminder system not running"}
        coro = delete_reminder(reminder_id)
        loop = cast(asyncio.AbstractEventLoop, self._loop)
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return fut.result()