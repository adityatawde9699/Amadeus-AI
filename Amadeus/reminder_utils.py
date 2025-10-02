# reminder_utils.py

from typing import Dict, List
from db import SessionLocal, init_db
import models
from sqlalchemy.orm import Session
from datetime import datetime
import dateparser
from speech_utils import speak
import threading


# Initialize DB tables
init_db()


def _get_session() -> Session:
    return SessionLocal()


def add_reminder(title: str, time_str: str, description: str = "") -> Dict:
    """Add a reminder. time_str can be natural language; we'll store ISO string."""
    parsed = dateparser.parse(time_str)
    if not parsed:
        return {"status": "error", "message": "Invalid date/time provided."}
    if parsed < datetime.now():
        return {"status": "error", "message": "Cannot set reminder for a past time."}
    with _get_session() as db:
        reminder = models.Reminder(title=title, time=parsed.isoformat(), description=description)
        db.add(reminder)
        db.commit()
        db.refresh(reminder)
        return {"status": "success", "message": f"Reminder set for {title} at {parsed.isoformat()}", "id": reminder.id}


def list_reminders() -> List[Dict]:
    with _get_session() as db:
        reminders = db.query(models.Reminder).filter(models.Reminder.status == 'active').order_by(models.Reminder.created_at.desc()).all()
        return [{"id": r.id, "title": r.title, "time": r.time, "description": r.description, "status": r.status} for r in reminders]


def delete_reminder(reminder_id: int) -> Dict:
    with _get_session() as db:
        rem = db.query(models.Reminder).get(reminder_id)
        if not rem:
            return {"status": "error", "message": "Reminder not found."}
        db.delete(rem)
        db.commit()
        return {"status": "success", "message": f"Reminder {reminder_id} deleted."}


def _check_due_reminders():
    """Check due reminders and speak them. Run periodically in a background thread."""
    while True:
        with _get_session() as db:
            now = datetime.utcnow()
            due = db.query(models.Reminder).filter(models.Reminder.status == 'active').all()
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
                    setattr(r, 'status', 'completed')
                    db.add(r)
            db.commit()
        # Sleep for 30 seconds before next check
        threading.Event().wait(30)


# Start background checker in daemon thread
_reminder_thread = threading.Thread(target=_check_due_reminders, daemon=True)
_reminder_thread.start()
