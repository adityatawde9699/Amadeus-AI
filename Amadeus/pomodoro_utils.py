# pomodoro_utils.py
"""
Pomodoro timer functionality for Amadeus AI Assistant.
Implements focus sessions with configurable work/break intervals.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Any
from dataclasses import dataclass, field

import config

logger = logging.getLogger(__name__)


@dataclass
class PomodoroSession:
    """Represents an active Pomodoro session."""
    task_name: str
    duration_minutes: int
    start_time: datetime
    session_type: str = "work"  # work, short_break, long_break
    completed: bool = False
    cancelled: bool = False
    
    @property
    def end_time(self) -> datetime:
        return self.start_time + timedelta(minutes=self.duration_minutes)
    
    @property
    def remaining_seconds(self) -> int:
        if self.completed or self.cancelled:
            return 0
        remaining = (self.end_time - datetime.now(timezone.utc)).total_seconds()
        return max(0, int(remaining))
    
    @property
    def is_active(self) -> bool:
        return not self.completed and not self.cancelled and self.remaining_seconds > 0


class PomodoroManager:
    """
    Manages Pomodoro sessions with background monitoring.
    
    The Pomodoro Technique uses focused work intervals (typically 25 minutes)
    followed by short breaks (5 minutes). After 4 sessions, take a longer break.
    """
    
    def __init__(self):
        self.current_session: Optional[PomodoroSession] = None
        self.completed_sessions: int = 0
        self.today_sessions: int = 0
        self.today_date: Optional[str] = None
        self._monitor_task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._callback: Optional[callable] = None
    
    def start_pomodoro(
        self,
        task_name: str = "Focus Session",
        duration_minutes: Optional[int] = None
    ) -> str:
        """
        Start a new Pomodoro focus session.
        
        Args:
            task_name: Description of what you're working on
            duration_minutes: Session length (default from config: 25 minutes)
        
        Returns:
            Status message
        """
        if self.current_session and self.current_session.is_active:
            remaining = self.current_session.remaining_seconds
            mins, secs = divmod(remaining, 60)
            return f"A Pomodoro session is already active! {mins}:{secs:02d} remaining on '{self.current_session.task_name}'."
        
        duration = duration_minutes or getattr(config, 'POMODORO_DEFAULT_DURATION', 25)
        
        self.current_session = PomodoroSession(
            task_name=task_name,
            duration_minutes=duration,
            start_time=datetime.now(timezone.utc),
            session_type="work"
        )
        
        # Reset daily counter if new day
        today = datetime.now().strftime("%Y-%m-%d")
        if self.today_date != today:
            self.today_date = today
            self.today_sessions = 0
        
        logger.info(f"Started Pomodoro: {task_name} for {duration} minutes")
        return f"Started {duration}-minute Pomodoro session: '{task_name}'. Stay focused! I'll notify you when it's time for a break."
    
    def stop_pomodoro(self) -> str:
        """Stop the current Pomodoro session."""
        if not self.current_session or not self.current_session.is_active:
            return "No active Pomodoro session to stop."
        
        self.current_session.cancelled = True
        task_name = self.current_session.task_name
        logger.info(f"Cancelled Pomodoro: {task_name}")
        return f"Cancelled the Pomodoro session: '{task_name}'."
    
    def complete_pomodoro(self) -> str:
        """Mark the current session as completed (called when timer ends)."""
        if not self.current_session:
            return ""
        
        self.current_session.completed = True
        self.completed_sessions += 1
        self.today_sessions += 1
        
        task_name = self.current_session.task_name
        
        # Determine break type
        sessions_before_long = getattr(config, 'POMODORO_SESSIONS_BEFORE_LONG_BREAK', 4)
        if self.completed_sessions % sessions_before_long == 0:
            break_duration = getattr(config, 'POMODORO_LONG_BREAK', 15)
            break_type = "long"
        else:
            break_duration = getattr(config, 'POMODORO_SHORT_BREAK', 5)
            break_type = "short"
        
        message = (
            f"Great work! Pomodoro session '{task_name}' complete. "
            f"You've completed {self.today_sessions} session{'s' if self.today_sessions != 1 else ''} today. "
            f"Time for a {break_duration}-minute {break_type} break!"
        )
        
        logger.info(f"Completed Pomodoro: {task_name}. Total today: {self.today_sessions}")
        return message
    
    def get_pomodoro_status(self) -> str:
        """Check the status of the current Pomodoro session."""
        if not self.current_session:
            return "No Pomodoro session active. Say 'start pomodoro' to begin a focus session."
        
        if not self.current_session.is_active:
            return "Last Pomodoro session has ended. Say 'start pomodoro' for a new session."
        
        remaining = self.current_session.remaining_seconds
        mins, secs = divmod(remaining, 60)
        
        return (
            f"Pomodoro active: '{self.current_session.task_name}'. "
            f"{mins}:{secs:02d} remaining. "
            f"Sessions completed today: {self.today_sessions}."
        )
    
    def get_pomodoro_stats(self) -> str:
        """Get productivity statistics."""
        today = datetime.now().strftime("%Y-%m-%d")
        today_count = self.today_sessions if self.today_date == today else 0
        
        # Calculate total focus time today
        duration = getattr(config, 'POMODORO_DEFAULT_DURATION', 25)
        total_minutes = today_count * duration
        hours, mins = divmod(total_minutes, 60)
        
        if today_count == 0:
            return "No Pomodoro sessions completed today. Start one to boost your productivity!"
        
        time_str = f"{hours}h {mins}m" if hours > 0 else f"{mins} minutes"
        
        return (
            f"Today's Pomodoro stats: {today_count} session{'s' if today_count != 1 else ''} completed. "
            f"Total focus time: {time_str}. "
            f"Lifetime sessions: {self.completed_sessions}."
        )
    
    def start_break(self, break_type: str = "short") -> str:
        """Start a break timer."""
        if break_type == "long":
            duration = getattr(config, 'POMODORO_LONG_BREAK', 15)
        else:
            duration = getattr(config, 'POMODORO_SHORT_BREAK', 5)
        
        self.current_session = PomodoroSession(
            task_name="Break Time",
            duration_minutes=duration,
            start_time=datetime.now(timezone.utc),
            session_type=f"{break_type}_break"
        )
        
        return f"Starting {duration}-minute {break_type} break. Relax and recharge!"


# Global Pomodoro manager instance
_pomodoro_manager: Optional[PomodoroManager] = None


def get_pomodoro_manager() -> PomodoroManager:
    """Get the global Pomodoro manager instance."""
    global _pomodoro_manager
    if _pomodoro_manager is None:
        _pomodoro_manager = PomodoroManager()
    return _pomodoro_manager


# ============================================================================
# ASYNC WRAPPER FUNCTIONS FOR TOOL REGISTRATION
# ============================================================================

async def start_pomodoro(task_name: str = "Focus Session", duration_minutes: Optional[int] = None) -> str:
    """Start a Pomodoro focus session. Args: task_name (str), duration_minutes (int, optional)."""
    manager = get_pomodoro_manager()
    return manager.start_pomodoro(task_name, duration_minutes)


async def stop_pomodoro() -> str:
    """Stop the current Pomodoro session."""
    manager = get_pomodoro_manager()
    return manager.stop_pomodoro()


async def get_pomodoro_status() -> str:
    """Get the status of the current Pomodoro session."""
    manager = get_pomodoro_manager()
    return manager.get_pomodoro_status()


async def get_pomodoro_stats() -> str:
    """Get Pomodoro productivity statistics."""
    manager = get_pomodoro_manager()
    return manager.get_pomodoro_stats()


async def start_break(break_type: str = "short") -> str:
    """Start a break timer. Args: break_type (str: 'short' or 'long')."""
    manager = get_pomodoro_manager()
    return manager.start_break(break_type)
