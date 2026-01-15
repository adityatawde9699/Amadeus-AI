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
        pass
    
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
        pass
    
    @abstractmethod
    async def create(self, entity: T) -> T:
        """
        Create a new entity.
        
        Args:
            entity: The entity to create.
            
        Returns:
            The created entity with its ID populated.
        """
        pass
    
    @abstractmethod
    async def update(self, entity: T) -> T:
        """
        Update an existing entity.
        
        Args:
            entity: The entity to update (must have an ID).
            
        Returns:
            The updated entity.
        """
        pass
    
    @abstractmethod
    async def delete(self, entity_id: int) -> bool:
        """
        Delete an entity by its ID.
        
        Args:
            entity_id: The entity's primary key.
            
        Returns:
            True if deleted, False if not found.
        """
        pass
    
    @abstractmethod
    async def count(self) -> int:
        """
        Count total entities.
        
        Returns:
            Total number of entities.
        """
        pass


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
        pass
    
    @abstractmethod
    async def get_pending(self) -> list[Task]:
        """Get all pending tasks."""
        pass
    
    @abstractmethod
    async def get_completed(self) -> list[Task]:
        """Get all completed tasks."""
        pass
    
    @abstractmethod
    async def mark_complete(self, task_id: int) -> Task | None:
        """
        Mark a task as completed.
        
        Args:
            task_id: The task's primary key.
            
        Returns:
            The updated task, or None if not found.
        """
        pass
    
    @abstractmethod
    async def get_summary(self) -> dict:
        """
        Get a summary of tasks.
        
        Returns:
            Dict with counts: total, pending, completed.
        """
        pass


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
        pass
    
    @abstractmethod
    async def get_by_tag(self, tag: str) -> list[Note]:
        """
        Get notes with a specific tag.
        
        Args:
            tag: The tag to filter by.
            
        Returns:
            List of notes with the given tag.
        """
        pass
    
    @abstractmethod
    async def get_recent(self, limit: int = 10) -> list[Note]:
        """
        Get the most recently updated notes.
        
        Args:
            limit: Maximum number of notes to return.
            
        Returns:
            List of recent notes.
        """
        pass
    
    @abstractmethod
    async def get_summary(self) -> dict:
        """
        Get a summary of notes.
        
        Returns:
            Dict with counts and tag statistics.
        """
        pass


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
        pass
    
    @abstractmethod
    async def get_active(self) -> list[Reminder]:
        """Get all active reminders."""
        pass
    
    @abstractmethod
    async def get_due(self, as_of: datetime | None = None) -> list[Reminder]:
        """
        Get reminders that are due.
        
        Args:
            as_of: The reference time (defaults to now).
            
        Returns:
            List of due reminders.
        """
        pass
    
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
        pass
    
    @abstractmethod
    async def mark_complete(self, reminder_id: int) -> Reminder | None:
        """Mark a reminder as completed."""
        pass
    
    @abstractmethod
    async def cancel(self, reminder_id: int) -> Reminder | None:
        """Cancel a reminder."""
        pass


# =============================================================================
# CALENDAR EVENT REPOSITORY
# =============================================================================

class ICalendarEventRepository(IRepository[CalendarEvent]):
    """Repository interface for CalendarEvent entities."""
    
    @abstractmethod
    async def get_by_status(self, status: EventStatus) -> list[CalendarEvent]:
        """Get events filtered by status."""
        pass
    
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
        pass
    
    @abstractmethod
    async def get_today(self) -> list[CalendarEvent]:
        """Get today's events."""
        pass
    
    @abstractmethod
    async def get_upcoming(self, hours_ahead: int = 24) -> list[CalendarEvent]:
        """Get upcoming events within a time window."""
        pass
    
    @abstractmethod
    async def get_by_title(self, title: str) -> list[CalendarEvent]:
        """Search events by title."""
        pass
    
    @abstractmethod
    async def cancel(self, event_id: int) -> CalendarEvent | None:
        """Cancel an event."""
        pass
    
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
        pass
