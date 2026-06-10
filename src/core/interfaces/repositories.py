"""
Repository interfaces for Amadeus AI Assistant.

These abstract base classes define the contracts for data access.
Each repository handles persistence for a specific domain entity.

Usage:
    from src.core.interfaces.repositories import ITaskRepository

    class SQLAlchemyTaskRepository(ITaskRepository):
        async def create(self, task: Task) -> Task:
            # Implementation using SQLAlchemy
            ...
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Generic, TypeVar

from src.core.domain.models import (
    CalendarEvent,
    EventStatus,
    Goal,
    GoalStatus,
    Note,
    Reminder,
    ReminderStatus,
    Task,
    TaskStatus,
)


# =============================================================================
# GENERIC REPOSITORY
# =============================================================================

T = TypeVar("T")


class IRepository(ABC, Generic[T]):
    """
    Generic repository interface for basic CRUD operations.

    Type parameter T represents the domain entity type.
    """

    @abstractmethod
    async def get_by_id(self, entity_id: int) -> T | None:
        """
        Get an entity by its ID.

        Args:
            entity_id: The entity's primary key.

        Returns:
            The entity if found, None otherwise.
        """

    @abstractmethod
    async def get_all(self, limit: int | None = None, offset: int = 0) -> list[T]:
        """
        Get all entities with optional pagination.

        Args:
            limit: Maximum number of entities to return.
            offset: Number of entities to skip.

        Returns:
            List of entities.
        """

    @abstractmethod
    async def create(self, entity: T) -> T:
        """
        Create a new entity.

        Args:
            entity: The entity to create.

        Returns:
            The created entity with its ID populated.
        """

    @abstractmethod
    async def update(self, entity: T) -> T:
        """
        Update an existing entity.

        Args:
            entity: The entity to update (must have an ID).

        Returns:
            The updated entity.
        """

    @abstractmethod
    async def delete(self, entity_id: int) -> bool:
        """
        Delete an entity by its ID.

        Args:
            entity_id: The entity's primary key.

        Returns:
            True if deleted, False if not found.
        """

    @abstractmethod
    async def count(self) -> int:
        """
        Count total entities.

        Returns:
            Total number of entities.
        """


# =============================================================================
# TASK REPOSITORY
# =============================================================================


class ITaskRepository(IRepository[Task]):
    """Repository interface for Task entities."""

    @abstractmethod
    async def get_by_status(self, status: TaskStatus) -> list[Task]:
        """
        Get tasks filtered by status.

        Args:
            status: The task status to filter by.

        Returns:
            List of tasks with the given status.
        """

    @abstractmethod
    async def get_pending(self) -> list[Task]:
        """Get all pending tasks."""

    @abstractmethod
    async def get_completed(self) -> list[Task]:
        """Get all completed tasks."""

    @abstractmethod
    async def mark_complete(self, task_id: int) -> Task | None:
        """
        Mark a task as completed.

        Args:
            task_id: The task's primary key.

        Returns:
            The updated task, or None if not found.
        """

    @abstractmethod
    async def get_summary(self) -> dict:
        """
        Get a summary of tasks.

        Returns:
            Dict with counts: total, pending, completed.
        """


# =============================================================================
# GOAL REPOSITORY
# =============================================================================


class IGoalRepository(IRepository[Goal]):
    """Repository interface for Goal entities."""

    @abstractmethod
    async def get_by_status(self, status: GoalStatus) -> list[Goal]:
        """Get goals filtered by status."""

    @abstractmethod
    async def get_active(self) -> list[Goal]:
        """Get all active goals."""

    @abstractmethod
    async def get_completed(self) -> list[Goal]:
        """Get all completed goals."""

    @abstractmethod
    async def mark_complete(self, goal_id: int) -> Goal | None:
        """Mark a goal as completed."""


# =============================================================================
# NOTE REPOSITORY
# =============================================================================


class INoteRepository(IRepository[Note]):
    """Repository interface for Note entities."""

    @abstractmethod
    async def search(self, query: str) -> list[Note]:
        """
        Search notes by title or content.

        Args:
            query: The search query.

        Returns:
            List of matching notes.
        """

    @abstractmethod
    async def get_by_tag(self, tag: str) -> list[Note]:
        """
        Get notes with a specific tag.

        Args:
            tag: The tag to filter by.

        Returns:
            List of notes with the given tag.
        """

    @abstractmethod
    async def get_recent(self, limit: int = 10) -> list[Note]:
        """
        Get the most recently updated notes.

        Args:
            limit: Maximum number of notes to return.

        Returns:
            List of recent notes.
        """

    @abstractmethod
    async def get_summary(self) -> dict:
        """
        Get a summary of notes.

        Returns:
            Dict with counts and tag statistics.
        """


# =============================================================================
# REMINDER REPOSITORY
# =============================================================================


class IReminderRepository(IRepository[Reminder]):
    """Repository interface for Reminder entities."""

    @abstractmethod
    async def get_by_status(self, status: ReminderStatus) -> list[Reminder]:
        """
        Get reminders filtered by status.

        Args:
            status: The reminder status to filter by.

        Returns:
            List of reminders with the given status.
        """

    @abstractmethod
    async def get_active(self) -> list[Reminder]:
        """Get all active reminders."""

    @abstractmethod
    async def get_due(self, as_of: datetime | None = None) -> list[Reminder]:
        """
        Get reminders that are due.

        Args:
            as_of: The reference time (defaults to now).

        Returns:
            List of due reminders.
        """

    @abstractmethod
    async def get_upcoming(
        self,
        hours_ahead: int = 24,
    ) -> list[Reminder]:
        """
        Get upcoming reminders within a time window.

        Args:
            hours_ahead: How many hours to look ahead.

        Returns:
            List of upcoming reminders.
        """

    @abstractmethod
    async def mark_complete(self, reminder_id: int) -> Reminder | None:
        """Mark a reminder as completed."""

    @abstractmethod
    async def cancel(self, reminder_id: int) -> Reminder | None:
        """Cancel a reminder."""


# =============================================================================
# CALENDAR EVENT REPOSITORY
# =============================================================================


class ICalendarEventRepository(IRepository[CalendarEvent]):
    """Repository interface for CalendarEvent entities."""

    @abstractmethod
    async def get_by_status(self, status: EventStatus) -> list[CalendarEvent]:
        """Get events filtered by status."""

    @abstractmethod
    async def get_by_date_range(
        self,
        start: datetime,
        end: datetime,
    ) -> list[CalendarEvent]:
        """
        Get events within a date range.

        Args:
            start: Start of the range (inclusive).
            end: End of the range (inclusive).

        Returns:
            List of events in the range.
        """

    @abstractmethod
    async def get_today(self) -> list[CalendarEvent]:
        """Get today's events."""

    @abstractmethod
    async def get_upcoming(self, hours_ahead: int = 24) -> list[CalendarEvent]:
        """Get upcoming events within a time window."""

    @abstractmethod
    async def get_by_title(self, title: str) -> list[CalendarEvent]:
        """Search events by title."""

    @abstractmethod
    async def cancel(self, event_id: int) -> CalendarEvent | None:
        """Cancel an event."""

    @abstractmethod
    async def get_summary(
        self,
        days_ahead: int = 7,
    ) -> dict:
        """
        Get a summary of upcoming events.

        Returns:
            Dict with counts and upcoming event details.
        """


# =============================================================================
# CONVERSATION REPOSITORY
# =============================================================================


class IConversationRepository(ABC):
    """Repository interface for conversation history persistence."""

    @abstractmethod
    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_used: str | None = None,
    ) -> None:
        """
        Add a message to the conversation history.

        Args:
            session_id: Session identifier to group messages.
            role: 'user' or 'assistant'.
            content: Message content.
            tool_used: Optional tool that was used.
        """

    @abstractmethod
    async def get_recent_context(
        self,
        session_id: str,
        limit: int = 10,
    ) -> list[dict]:
        """
        Get recent messages for context.

        Args:
            session_id: The session to retrieve messages for.
            limit: Maximum number of messages to return.

        Returns:
            List of message dicts with role, content, tool_used, timestamp.
        """

    @abstractmethod
    async def get_session_history(self, session_id: str) -> list[dict]:
        """Get all messages for a session."""

    @abstractmethod
    async def clear_session(self, session_id: str) -> int:
        """
        Clear all messages for a session.

        Returns:
            Number of messages deleted.
        """

    @abstractmethod
    async def list_sessions(self, limit: int = 20) -> list[str]:
        """
        List recent session IDs.

        Returns:
            List of session IDs ordered by recency.
        """


# =============================================================================
# POMODORO REPOSITORY
# =============================================================================

from src.core.domain.models import PomodoroSession, PomodoroState


class IPomodoroRepository(ABC):
    """Repository interface for Pomodoro session persistence."""

    @abstractmethod
    async def create(self, session_model: PomodoroSession) -> PomodoroSession:
        """Insert a new Pomodoro session and return the persisted record."""

    @abstractmethod
    async def get_by_id(self, session_id: int) -> PomodoroSession | None:
        """Fetch a single Pomodoro session by primary key."""

    @abstractmethod
    async def get_active(self) -> PomodoroSession | None:
        """Return the active/running session (working/break/paused), or None."""

    @abstractmethod
    async def update_state(
        self,
        session_id: int,
        new_state: PomodoroState,
        cycles_completed: int | None = None,
    ) -> PomodoroSession | None:
        """Transition a Pomodoro session to a new state."""

    @abstractmethod
    async def list_recent(self, limit: int = 10) -> list[PomodoroSession]:
        """Return the N most recent Pomodoro sessions."""

    @abstractmethod
    async def count_completed_today(self) -> int:
        """Count Pomodoro cycles completed today (UTC)."""


# =============================================================================
# KNOWLEDGE GRAPH REPOSITORY
# =============================================================================


class IKnowledgeGraphRepository(ABC):
    """Repository interface for Knowledge Graph (Episodic Memory)."""

    @abstractmethod
    async def upsert_entity(
        self, name: str, entity_type: str | None = None, description: str | None = None
    ) -> int:
        """
        Create or update an entity by name.

        Returns:
            The entity ID.
        """

    @abstractmethod
    async def add_relationship(self, subject_id: int, predicate: str, object_id: int) -> None:
        """
        Add or strengthen a relationship between two entities.
        """

    @abstractmethod
    async def find_relationships_by_entity(self, entity_name: str) -> list[dict]:
        """
        Find all relationships where the given entity is either subject or object.

        Returns:
            List of triples: {"subject": str, "predicate": str, "object": str}
        """

    @abstractmethod
    async def get_entity_by_name(self, name: str) -> dict | None:
        """Get entity details by name."""
