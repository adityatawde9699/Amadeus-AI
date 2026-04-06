"""
SQLAlchemy ORM models for Amadeus AI Assistant.

These models map domain entities to database tables. They are separate
from the domain models in src/core/domain/models.py which are pure
Pydantic models.

The ORM models handle database-specific concerns like:
- Primary keys and autoincrement
- Indexes for query optimization
- SQLAlchemy column types and constraints

Migrated to SQLAlchemy 2.0 Mapped/mapped_column style for full type safety.
"""

import enum
from datetime import datetime

from sqlalchemy import Index, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.infra.persistence.database import Base


# =============================================================================
# ENUMS (SQLAlchemy compatible)
# =============================================================================

class UserRoleDB(enum.StrEnum):
    """RBAC Role enum for database."""
    ADMIN = "admin"
    USER = "user"
    GUEST = "guest"

class TaskStatusDB(enum.StrEnum):
    """Task status enum for database."""
    PENDING = "pending"
    COMPLETED = "completed"


class ReminderStatusDB(enum.StrEnum):
    """Reminder status enum for database."""
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class EventStatusDB(enum.StrEnum):
    """Calendar event status enum for database."""
    ACTIVE = "active"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


# =============================================================================
# ORM MODELS
# =============================================================================

class UserORM(Base):
    """ORM model for users and RBAC."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))

    # RBAC Fields
    role: Mapped[UserRoleDB] = mapped_column(
        SAEnum(UserRoleDB),
        default=UserRoleDB.USER,
    )
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)

    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username}, role={self.role.value})>"

class TaskORM(Base):
    """ORM model for tasks/todos."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[TaskStatusDB] = mapped_column(
        SAEnum(TaskStatusDB),
        default=TaskStatusDB.PENDING,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        index=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True, index=True)

    __table_args__ = (
        Index("idx_task_status_created", "status", "created_at"),
        Index("idx_task_status_completed", "status", "completed_at"),
    )

    def __repr__(self) -> str:
        return f"<Task(id={self.id}, status={self.status.value})>"


class NoteORM(Base):
    """ORM model for notes."""

    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(256), index=True)
    content: Mapped[str] = mapped_column(Text)
    tags: Mapped[str] = mapped_column(String(512), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        index=True,
    )
    updated_at: Mapped[datetime | None] = mapped_column(
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

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(256))
    time: Mapped[datetime] = mapped_column(index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[ReminderStatusDB] = mapped_column(
        SAEnum(ReminderStatusDB),
        default=ReminderStatusDB.ACTIVE,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        index=True,
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

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    start_time: Mapped[datetime] = mapped_column(index=True)
    end_time: Mapped[datetime] = mapped_column(index=True)
    location: Mapped[str] = mapped_column(String(256), default="")
    all_day: Mapped[bool] = mapped_column(default=False)
    recurrence: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[EventStatusDB] = mapped_column(
        SAEnum(EventStatusDB),
        default=EventStatusDB.ACTIVE,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        index=True,
    )
    updated_at: Mapped[datetime | None] = mapped_column(
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

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        index=True,
    )
    source: Mapped[str] = mapped_column(String(32), index=True)  # voice, text, api
    interaction_type: Mapped[str] = mapped_column(String(32), default="conversation")
    input_text: Mapped[str] = mapped_column(Text)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    intent_detected: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    tool_used: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    success: Mapped[bool] = mapped_column(default=False, index=True)
    execution_time_ms: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_log_source_timestamp", "source", "timestamp"),
        Index("idx_log_intent_timestamp", "intent_detected", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<InteractionLog(id={self.id}, source={self.source})>"


class MessageORM(Base):
    """ORM model for conversation messages (for persistence across restarts)."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    role: Mapped[str] = mapped_column(String(16))  # 'user' or 'assistant'
    content: Mapped[str] = mapped_column(Text)
    tool_used: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        index=True,
    )

    __table_args__ = (
        Index("idx_message_session_timestamp", "session_id", "timestamp"),
        Index("idx_message_role_timestamp", "role", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, role={self.role}, session={self.session_id[:8]}...)>"


# =============================================================================
# POMODORO MODELS
# =============================================================================

class PomodoroStateDB(enum.StrEnum):
    """Pomodoro session state enum for database."""
    IDLE = "idle"
    WORKING = "working"
    SHORT_BREAK = "short_break"
    LONG_BREAK = "long_break"
    COMPLETED = "completed"
    PAUSED = "paused"


class PomodoroSessionORM(Base):
    """ORM model for Pomodoro timer sessions.

    Each row represents one Pomodoro work session. Cycles accumulate
    until the long break threshold is reached.
    """

    __tablename__ = "pomodoro_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    state: Mapped[PomodoroStateDB] = mapped_column(
        SAEnum(PomodoroStateDB),
        default=PomodoroStateDB.IDLE,
        index=True,
    )
    task_description: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    work_duration_minutes: Mapped[int] = mapped_column(default=25)
    short_break_minutes: Mapped[int] = mapped_column(default=5)
    long_break_minutes: Mapped[int] = mapped_column(default=15)
    cycles_completed: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        index=True,
    )

    __table_args__ = (
        Index("idx_pomodoro_state_created", "state", "created_at"),
        Index("idx_pomodoro_started_state", "started_at", "state"),
    )

    def __repr__(self) -> str:
        return f"<PomodoroSession(id={self.id}, state={self.state.value}, cycles={self.cycles_completed})>"


# =============================================================================
# PROCESSED EMAIL (State Tracking)
# =============================================================================

class ProcessedEmailORM(Base):
    """
    Tracks which emails the agent has already read and processed.

    Indexed by RFC 822 Message-ID to prevent re-processing.
    """

    __tablename__ = "processed_emails"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    subject: Mapped[str] = mapped_column(String(1024), default="")
    sender: Mapped[str] = mapped_column(String(512), default="")
    action_taken: Mapped[str] = mapped_column(String(256), default="read")
    processed_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"<ProcessedEmail(id={self.id}, message_id={self.message_id!r})>"


# =============================================================================
# CONVERSATION SUMMARY (Rolling Memory)
# =============================================================================

class ConversationSummaryORM(Base):
    """
    Stores rolling LLM-generated summaries of conversation history.

    Each row represents a snapshot of the condensed conversation memory.
    The latest row is injected into the LLM system prompt.
    """

    __tablename__ = "conversation_summaries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    messages_summarized: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        index=True,
    )

    def __repr__(self) -> str:
        return f"<ConversationSummary(id={self.id}, msgs={self.messages_summarized})>"


# =============================================================================
# KNOWLEDGE GRAPH (Episodic Memory)
# =============================================================================

class EntityORM(Base):
    """
    ORM model for entities in the Knowledge Graph.
    Entities represent people, places, objects, or concepts the user mentions.
    """
    __tablename__ = "graph_entities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(64), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("idx_entity_name_type", "name", "entity_type"),
    )

    def __repr__(self) -> str:
        return f"<Entity(name='{self.name}', type='{self.entity_type}')>"


class RelationshipORM(Base):
    """
    ORM model for relationships in the Knowledge Graph (SPO Triples).
    Subject -> Predicate -> Object
    """
    __tablename__ = "graph_relationships"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    subject_id: Mapped[int] = mapped_column(index=True)
    predicate: Mapped[str] = mapped_column(String(128), index=True)
    object_id: Mapped[int] = mapped_column(index=True)

    strength: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("idx_rel_triple", "subject_id", "predicate", "object_id"),
        Index("idx_rel_predicate", "predicate"),
    )

    def __repr__(self) -> str:
        return f"<Relationship(sub={self.subject_id}, pred='{self.predicate}', obj={self.object_id})>"
