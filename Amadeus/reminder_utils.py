# reminder_utils.py

import datetime
import json
import uuid
from typing import Dict, List
import threading
import time
import os
from speech_utils import speak # Import the speak function

REMINDERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reminders.json")

class ReminderManager:
    def __init__(self):
        self.reminders: Dict = {}
        self.load_reminders()
        # Use a threading.Event for safer start/stop control
        self._stop_event = threading.Event()
        self.reminder_thread = None

    def load_reminders(self):
        try:
            with open(REMINDERS_FILE, 'r') as f:
                self.reminders = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.reminders = {}
            self.save_reminders()

    def save_reminders(self):
        with open(REMINDERS_FILE, 'w') as f:
            json.dump(self.reminders, f, indent=2)

    def add_reminder(self, title: str, datetime_str: str, description: str = "") -> dict:
        try:
            reminder_time = datetime.datetime.strptime(datetime_str, "%d-%m-%Y %H:%M")
            if reminder_time < datetime.datetime.now():
                return {"status": "error", "message": "Cannot set reminder for a past time."}

            reminder_id = str(uuid.uuid4())[:8]
            self.reminders[reminder_id] = {
                "title": title,
                "time": datetime_str,
                "description": description,
                "status": "active"
            }
            self.save_reminders()
            return {"status": "success", "message": f"Reminder set for {title} at {datetime_str}", "id": reminder_id}
        except ValueError:
            return {"status": "error", "message": "Invalid date format. Please use DD-MM-YYYY HH:MM"}

    def list_reminders(self) -> List[dict]:
        return [v for v in self.reminders.values() if v["status"] == "active"]

    def delete_reminder(self, reminder_id: str) -> dict:
        if reminder_id in self.reminders:
            del self.reminders[reminder_id]
            self.save_reminders()
            return {"status": "success", "message": f"Reminder {reminder_id} deleted."}
        return {"status": "error", "message": "Reminder not found."}

    def _check_reminders(self):
        """The background thread function to check for due reminders."""
        while not self._stop_event.is_set():
            now = datetime.datetime.now()
            # Iterate over a copy of items to avoid runtime errors if the dict changes
            for reminder_id, reminder in list(self.reminders.items()):
                if reminder["status"] == "active":
                    reminder_time = datetime.datetime.strptime(reminder["time"], "%d-%m-%Y %H:%M")
                    if now >= reminder_time:
                        # Construct and speak the reminder message
                        message = f"Reminder: {reminder['title']}."
                        if reminder["description"]:
                            message += f" Here is the description: {reminder['description']}"
                        
                        print(f"🔔 {message}") # Also print to console
                        speak(message)
                        
                        # Update status and save
                        reminder["status"] = "completed"
                        self.save_reminders()
            
            # Wait for 60 seconds or until the stop event is set
            self._stop_event.wait(60)

    def start_monitoring(self):
        if not self.reminder_thread or not self.reminder_thread.is_alive():
            self._stop_event.clear()
            self.reminder_thread = threading.Thread(target=self._check_reminders)
            self.reminder_thread.daemon = True
            self.reminder_thread.start()
            print("Reminder monitoring started.")

    def stop_monitoring(self):
        self._stop_event.set()
        if self.reminder_thread:
            self.reminder_thread.join()
        print("Reminder monitoring stopped.")