# reminder_utils.py

from typing import Dict, List, Optional
from db import get_async_session, init_db_async
import models
from datetime import datetime
import dateparser
from speech_utils import speak
import asyncio
import time
from typing import cast
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
            stmt = select(models.Reminder).where(models.Reminder.status == 'active').order_by(models.Reminder.created_at.desc())
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


class ReminderManager:
    """Compatibility wrapper that runs the async reminder loop in a background thread
    and exposes synchronous methods used by existing code (like `Amadeus`).
    """
    def __init__(self):
        # Types are initialized to None; wrapper will start a dedicated loop/thread
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = None
        self._stop_event: asyncio.Event | None = None

    def _ensure_loop_ready(self, timeout: float = 5.0) -> bool:
        """Wait (briefly) for the background thread to create the event loop.
        Returns True if loop was set, False on timeout.
        """
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
        loop = cast(asyncio.AbstractEventLoop, self._loop)
        fut = asyncio.run_coroutine_threadsafe(_set_event(), loop)
        try:
            fut.result(timeout=5)
        except Exception:
            pass
        self._thread.join(timeout=5)
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

