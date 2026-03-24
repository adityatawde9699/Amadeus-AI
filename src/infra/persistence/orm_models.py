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

class UserRoleDB(str, enum.Enum):
    """RBAC Role enum for database."""
    ADMIN = "admin"
    USER = "user"
    GUEST = "guest"

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

class UserORM(Base):
    """ORM model for users and RBAC."""
    
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    
    # RBAC Fields
    role = Column(
        SAEnum(UserRoleDB),
        default=UserRoleDB.USER,
        nullable=False,
    )
    tenant_id = Column(String(36), index=True, nullable=True) # Groups users together
    
    is_active = Column(Boolean, default=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username}, role={self.role.value})>"

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


class MessageORM(Base):
    """ORM model for conversation messages (for persistence across restarts)."""
    
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id = Column(String(36), nullable=False, index=True)  # Group messages by session
    role = Column(String(16), nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    tool_used = Column(String(128), nullable=True, index=True)
    timestamp = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
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

class PomodoroStateDB(str, enum.Enum):
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

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    state = Column(
        SAEnum(PomodoroStateDB),
        default=PomodoroStateDB.IDLE,
        nullable=False,
        index=True,
    )
    task_description = Column(Text, default="")
    started_at = Column(DateTime(timezone=True), nullable=True, index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    work_duration_minutes = Column(Integer, default=25, nullable=False)
    short_break_minutes = Column(Integer, default=5, nullable=False)
    long_break_minutes = Column(Integer, default=15, nullable=False)
    cycles_completed = Column(Integer, default=0, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
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

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(String(512), unique=True, nullable=False, index=True)
    subject = Column(String(1024), default="")
    sender = Column(String(512), default="")
    action_taken = Column(String(256), default="read")  # read | replied | ignored
    processed_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
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

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(256), nullable=True, index=True)
    summary = Column(Text, nullable=False, default="")
    messages_summarized = Column(Integer, default=0)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
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

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), nullable=False, index=True)
    entity_type = Column(String(64), index=True)  # person, place, project, etc.
    description = Column(Text, default="")
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
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

    id = Column(Integer, primary_key=True, autoincrement=True)
    subject_id = Column(Integer, index=True, nullable=False)  # Links to EntityORM.id
    predicate = Column(String(128), index=True, nullable=False) # is_boss_of, works_on, etc.
    object_id = Column(Integer, index=True, nullable=False)   # Links to EntityORM.id
    
    strength = Column(Integer, default=1) # To handle recurring mentions
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("idx_rel_triple", "subject_id", "predicate", "object_id"),
        Index("idx_rel_predicate", "predicate"),
    )

    def __repr__(self) -> str:
        return f"<Relationship(sub={self.subject_id}, pred='{self.predicate}', obj={self.object_id})>"


