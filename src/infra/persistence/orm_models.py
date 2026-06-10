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
# SQLAlchemy mapped_column() defaults are ORM column defs, not mutable attrs

import enum
from datetime import datetime

from sqlalchemy import Enum as SAEnum


# Helper: tell SQLAlchemy to use the StrEnum .value (lowercase) for DB I/O
# instead of .name (uppercase).  Without this, asyncpg sends e.g. 'WORKING'
# when the PostgreSQL enum type expects 'working', causing
# InvalidTextRepresentationError.
_enum_values = lambda e: [m.value for m in e]  # noqa: E731
from sqlalchemy import JSON, Float, ForeignKey, Index, Integer, String, Text
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


class GoalStatusDB(enum.StrEnum):
    """Goal status enum for database."""

    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


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


class CognitivePlanStatusDB(enum.StrEnum):
    """Cognitive execution plan status enum."""

    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CognitiveStepStatusDB(enum.StrEnum):
    """Cognitive execution step status enum."""

    PENDING = "pending"
    RUNNING = "running"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# =============================================================================
# ORM MODELS
# =============================================================================

from fastapi_users.db import SQLAlchemyBaseUserTable


class UserORM(SQLAlchemyBaseUserTable[int], Base):
    """ORM model for users and RBAC using fastapi-users."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)

    # The following are provided by SQLAlchemyBaseUserTable but can be overridden:
    # email: Mapped[str]
    # hashed_password: Mapped[str]
    # is_active: Mapped[bool]
    # is_superuser: Mapped[bool]
    # is_verified: Mapped[bool]

    # RBAC Fields
    role: Mapped[UserRoleDB] = mapped_column(
        SAEnum(UserRoleDB, values_callable=_enum_values),
        default=UserRoleDB.GUEST,
    )
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)

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
        SAEnum(TaskStatusDB, values_callable=_enum_values),
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


class GoalORM(Base):
    """ORM model for long-term goals."""

    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[GoalStatusDB] = mapped_column(
        SAEnum(GoalStatusDB, values_callable=_enum_values),
        default=GoalStatusDB.ACTIVE,
        index=True,
    )
    target_date: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        index=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    parent_goal_id: Mapped[int | None] = mapped_column(nullable=True, index=True)

    __table_args__ = (
        Index("idx_goal_status_created", "status", "created_at"),
        Index("idx_goal_status_target", "status", "target_date"),
    )

    def __repr__(self) -> str:
        return f"<Goal(id={self.id}, title='{self.title[:30]}', status={self.status.value})>"


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
        SAEnum(ReminderStatusDB, values_callable=_enum_values),
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
        SAEnum(EventStatusDB, values_callable=_enum_values),
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
        return (
            f"<CalendarEvent(id={self.id}, title='{self.title[:30]}', status={self.status.value})>"
        )


class InteractionLogORM(Base):
    """ORM model for interaction history."""

    __tablename__ = "interaction_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        index=True,
    )
    source: Mapped[str] = mapped_column(String(32), index=True)  # text, api
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
# COGNITIVE RUNTIME MODELS
# =============================================================================


class CognitivePlanORM(Base):
    """Durable execution plan for cognitive runtime tasks."""

    __tablename__ = "cognitive_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[str] = mapped_column(String(256), index=True)
    user_id: Mapped[str] = mapped_column(String(256), index=True)
    goal_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    original_task: Mapped[str] = mapped_column(Text)
    status: Mapped[CognitivePlanStatusDB] = mapped_column(
        SAEnum(CognitivePlanStatusDB, values_callable=_enum_values),
        default=CognitivePlanStatusDB.DRAFT,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    final_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
        index=True,
    )

    __table_args__ = (
        Index("idx_cognitive_plan_session_status", "session_id", "status"),
        Index("idx_cognitive_plan_request_status", "request_id", "status"),
    )


class CognitivePlanStepORM(Base):
    """Durable execution step within a cognitive plan."""

    __tablename__ = "cognitive_plan_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("cognitive_plans.id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text)
    tool: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    args: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[CognitiveStepStatusDB] = mapped_column(
        SAEnum(CognitiveStepStatusDB, values_callable=_enum_values),
        default=CognitiveStepStatusDB.PENDING,
        index=True,
    )
    dependencies: Mapped[list] = mapped_column(JSON, default=list)
    risk_level: Mapped[str] = mapped_column(String(32), default="low", index=True)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("idx_cognitive_step_plan_status", "plan_id", "status"),
        Index("idx_cognitive_step_tool_status", "tool", "status"),
    )


class CognitiveObservationORM(Base):
    """Durable observation from a tool, model, verifier, or external event."""

    __tablename__ = "cognitive_observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("cognitive_plans.id", ondelete="CASCADE"),
        index=True,
    )
    step_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("cognitive_plan_steps.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(128), index=True)
    content: Mapped[str] = mapped_column(Text)
    success: Mapped[bool] = mapped_column(default=True, index=True)
    observation_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)

    __table_args__ = (
        Index("idx_cognitive_observation_plan_created", "plan_id", "created_at"),
        Index("idx_cognitive_observation_step_created", "step_id", "created_at"),
    )


class CognitiveReflectionORM(Base):
    """Durable verifier/reflection result for a plan step."""

    __tablename__ = "cognitive_reflections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("cognitive_plans.id", ondelete="CASCADE"),
        index=True,
    )
    step_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("cognitive_plan_steps.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    analysis: Mapped[str] = mapped_column(Text)
    suggested_action: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_dead_end: Mapped[bool] = mapped_column(default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)

    __table_args__ = (
        Index("idx_cognitive_reflection_plan_created", "plan_id", "created_at"),
        Index("idx_cognitive_reflection_dead_end", "is_dead_end", "created_at"),
    )


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
        SAEnum(PomodoroStateDB, values_callable=_enum_values),
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


