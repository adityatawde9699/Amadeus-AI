"""
SQLAlchemy ORM models for Amadeus AI Assistant.

These models map domain entities to database tables. They are separate
from the domain models in src/core/domain/models.py which are pure
Pydantic models.

The ORM models handle database-specific concerns like:
- Primary keys and autoincrement
- Indexes for query optimization
- SQLAlchemy column types and constraints
"""

import enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum as SAEnum,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.sql import func

from src.infra.persistence.database import Base


# =============================================================================
# ENUMS (SQLAlchemy compatible)
# =============================================================================

class TaskStatusDB(str, enum.Enum):
    """Task status enum for database."""
    PENDING = "pending"
    COMPLETED = "completed"


class ReminderStatusDB(str, enum.Enum):
    """Reminder status enum for database."""
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class EventStatusDB(str, enum.Enum):
    """Calendar event status enum for database."""
    ACTIVE = "active"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


# =============================================================================
# ORM MODELS
# =============================================================================

class TaskORM(Base):
    """ORM model for tasks/todos."""
    
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    content = Column(Text, nullable=False)
    status = Column(
        SAEnum(TaskStatusDB),
        default=TaskStatusDB.PENDING,
        index=True,
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )
    completed_at = Column(DateTime(timezone=True), nullable=True, index=True)
    
    __table_args__ = (
        Index("idx_task_status_created", "status", "created_at"),
        Index("idx_task_status_completed", "status", "completed_at"),
    )
    
    def __repr__(self) -> str:
        return f"<Task(id={self.id}, status={self.status.value})>"


class NoteORM(Base):
    """ORM model for notes."""
    
    __tablename__ = "notes"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(256), nullable=False, index=True)
    content = Column(Text, nullable=False)
    tags = Column(String(512), default="", index=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        index=True,
    )
    
    __table_args__ = (
        Index("idx_note_tags_created", "tags", "created_at"),
        Index("idx_note_created_desc", "created_at"),
    )
    
    def __repr__(self) -> str:
        return f"<Note(id={self.id}, title='{self.title[:30]}...')>"


class ReminderORM(Base):
    """ORM model for reminders."""
    
    __tablename__ = "reminders"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(256), nullable=False)
    time = Column(DateTime(timezone=True), nullable=False, index=True)
    description = Column(Text, default="")
    status = Column(
        SAEnum(ReminderStatusDB),
        default=ReminderStatusDB.ACTIVE,
        index=True,
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )
    
    __table_args__ = (
        Index("idx_reminder_status_created", "status", "created_at"),
        Index("idx_reminder_status_time", "status", "time"),
    )
    
    def __repr__(self) -> str:
        return f"<Reminder(id={self.id}, title='{self.title[:30]}', status={self.status.value})>"


class CalendarEventORM(Base):
    """ORM model for calendar events."""
    
    __tablename__ = "calendar_events"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(256), nullable=False)
    description = Column(Text, default="")
    start_time = Column(DateTime(timezone=True), nullable=False, index=True)
    end_time = Column(DateTime(timezone=True), nullable=False, index=True)
    location = Column(String(256), default="")
    all_day = Column(Boolean, default=False)
    recurrence = Column(String(64), default="")
    status = Column(
        SAEnum(EventStatusDB),
        default=EventStatusDB.ACTIVE,
        index=True,
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    
    __table_args__ = (
        Index("idx_event_start_status", "start_time", "status"),
        Index("idx_event_date_range", "start_time", "end_time"),
        Index("idx_event_status_created", "status", "created_at"),
    )
    
    def __repr__(self) -> str:
        return f"<CalendarEvent(id={self.id}, title='{self.title[:30]}', status={self.status.value})>"


class InteractionLogORM(Base):
    """ORM model for interaction history."""
    
    __tablename__ = "interaction_logs"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    uuid = Column(String(36), nullable=False, unique=True, index=True)
    timestamp = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )
    source = Column(String(32), nullable=False, index=True)  # voice, text, api
    interaction_type = Column(String(32), default="conversation")
    input_text = Column(Text, nullable=False)
    response_text = Column(Text, nullable=True)
    intent_detected = Column(String(128), nullable=True, index=True)
    tool_used = Column(String(128), nullable=True, index=True)
    success = Column(Boolean, default=False, index=True)
    execution_time_ms = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    
    __table_args__ = (
        Index("idx_log_source_timestamp", "source", "timestamp"),
        Index("idx_log_intent_timestamp", "intent_detected", "timestamp"),
    )
    
    def __repr__(self) -> str:
        return f"<InteractionLog(id={self.id}, source={self.source})>"
