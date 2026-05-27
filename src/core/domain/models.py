"""
Domain models for Amadeus AI Assistant.

These are pure Pydantic models representing the core business entities.
They are independent of the database (ORM) and external services.

Usage:
    from src.core.domain.models import InteractionLog, RequestSource

    log = InteractionLog(
        source=RequestSource.VOICE,
        input_text="What time is it?"
    )
"""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# ENUMS
# =============================================================================


class PermissionProfile(StrEnum):
    """Declared permission profile for the agent session."""

    READ_ONLY = "read_only"
    SYSTEM_FULL = "system_full"


class RequestSource(StrEnum):
    """Source of the user's request."""

    VOICE = "voice"
    TEXT = "text"
    API = "api"
    DASHBOARD = "dashboard"


class InteractionType(StrEnum):
    """Type of interaction with the assistant."""

    COMMAND = "command"  # Execute a specific action
    QUERY = "query"  # Request information
    CONVERSATION = "conversation"  # General chat
    SYSTEM = "system"  # System-generated (reminders, alerts)


class TaskStatus(StrEnum):
    """Status of a task."""

    PENDING = "pending"
    COMPLETED = "completed"


class GoalStatus(StrEnum):
    """Status of a long-term goal."""

    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class ReminderStatus(StrEnum):
    """Status of a reminder."""

    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class EventStatus(StrEnum):
    """Status of a calendar event."""

    ACTIVE = "active"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class PomodoroState(StrEnum):
    """State of a Pomodoro session."""

    IDLE = "idle"
    WORKING = "working"
    SHORT_BREAK = "short_break"
    LONG_BREAK = "long_break"
    COMPLETED = "completed"
    PAUSED = "paused"


class AlertSeverity(StrEnum):
    """Severity level for system alerts."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


# =============================================================================
# CORE DOMAIN MODELS
# =============================================================================


class UserContext(BaseModel):
    """
    Context about who is speaking/interacting with Amadeus.

    In a multi-user system, this would include user ID, preferences,
    permissions, etc. For now, it's simplified for single-user use.
    """

    model_config = ConfigDict(frozen=True)

    user_id: str = "admin"
    timezone: str = "UTC"
    language: str = "en"
    location: str | None = None


class InteractionLog(BaseModel):
    """
    Represents a single exchange with Amadeus.

    This is the primary record of all interactions, whether from
    voice, text, or API. Used for logging, analytics, and context.
    """

    id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source: RequestSource
    interaction_type: InteractionType = InteractionType.CONVERSATION
    input_text: str
    response_text: str | None = None
    intent_detected: str | None = None
    tool_used: str | None = None
    tool_args: dict[str, Any] | None = None
    success: bool = False
    execution_time_ms: float = 0.0
    error_message: str | None = None
    user_context: UserContext = Field(default_factory=UserContext)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SystemStatus(BaseModel):
    """
    Health check model for system monitoring.

    Provides a snapshot of the current system state including
    resource usage and health indicators.
    """

    model_config = ConfigDict(frozen=True)

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    cpu_usage: float = Field(ge=0, le=100)
    memory_usage: float = Field(ge=0, le=100)
    disk_usage: float = Field(ge=0, le=100, default=0)
    battery_percent: float | None = Field(default=None, ge=0, le=100)
    is_charging: bool = False
    uptime_seconds: float = 0.0
    is_healthy: bool = True
    alerts: list[str] = Field(default_factory=list)


class SystemAlert(BaseModel):
    """
    Represents a system alert or warning.
    """

    id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    severity: AlertSeverity
    category: str  # e.g., "cpu", "memory", "disk", "battery"
    message: str
    value: float | None = None
    threshold: float | None = None
    acknowledged: bool = False


# =============================================================================
# PRODUCTIVITY DOMAIN MODELS
# =============================================================================


class Task(BaseModel):
    """Domain model for a task/todo item."""

    id: int | None = None
    content: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None

    def mark_complete(self) -> "Task":
        """Return a new Task marked as complete."""
        return self.model_copy(
            update={
                "status": TaskStatus.COMPLETED,
                "completed_at": datetime.utcnow(),
            }
        )


class Goal(BaseModel):
    """Domain model for a long-term goal."""

    id: int | None = None
    title: str
    description: str = ""
    status: GoalStatus = GoalStatus.ACTIVE
    target_date: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    parent_goal_id: int | None = None

    def mark_complete(self) -> "Goal":
        """Return a new Goal marked as complete."""
        return self.model_copy(
            update={
                "status": GoalStatus.COMPLETED,
                "completed_at": datetime.utcnow(),
            }
        )


class Note(BaseModel):
    """Domain model for a note."""

    id: int | None = None
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def tags_str(self) -> str:
        """Get tags as comma-separated string."""
        return ",".join(self.tags)


class Reminder(BaseModel):
    """Domain model for a reminder."""

    id: int | None = None
    title: str
    time: datetime
    description: str = ""
    status: ReminderStatus = ReminderStatus.ACTIVE
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def is_due(self) -> bool:
        """Check if reminder is due (past its scheduled time)."""
        return self.status == ReminderStatus.ACTIVE and datetime.utcnow() >= self.time


class CalendarEvent(BaseModel):
    """Domain model for a calendar event."""

    id: int | None = None
    title: str
    description: str = ""
    start_time: datetime
    end_time: datetime
    location: str = ""
    all_day: bool = False
    recurrence: str = ""
    status: EventStatus = EventStatus.ACTIVE
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def duration_minutes(self) -> int:
        """Get event duration in minutes."""
        delta = self.end_time - self.start_time
        return int(delta.total_seconds() / 60)

    @property
    def is_active(self) -> bool:
        """Check if event is currently active (now is between start and end)."""
        now = datetime.utcnow()
        return self.start_time <= now <= self.end_time


class PomodoroSession(BaseModel):
    """Domain model for a Pomodoro work session."""

    id: int | None = None
    state: PomodoroState = PomodoroState.IDLE
    task_description: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None
    work_duration_minutes: int = 25
    short_break_minutes: int = 5
    long_break_minutes: int = 15
    cycles_completed: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def is_running(self) -> bool:
        """Check if a session is currently active."""
        return self.state not in (PomodoroState.IDLE, PomodoroState.COMPLETED)


# =============================================================================
# TOOL DOMAIN MODELS
# =============================================================================


class ToolDefinition(BaseModel):
    """Definition of a tool/function that Amadeus can execute."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    category: str  # e.g., "system", "productivity", "information"
    parameters: dict[str, Any] = Field(default_factory=dict)
    requires_confirmation: bool = False
    is_async: bool = False


class ToolExecutionResult(BaseModel):
    """Result of executing a tool."""

    tool_name: str
    success: bool
    result: Any = None
    error_message: str | None = None
    execution_time_ms: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# CONVERSATION DOMAIN MODELS
# =============================================================================


class ConversationMessage(BaseModel):
    """A single message in a conversation."""

    role: str  # "user", "assistant", "system"
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    tool_used: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationContext(BaseModel):
    """Context for ongoing conversation."""

    messages: list[ConversationMessage] = Field(default_factory=list)
    user_context: UserContext = Field(default_factory=UserContext)
    summary: str = ""

    def add_message(
        self, role: str, content: str, tool_used: str | None = None, **metadata: Any
    ) -> None:
        """Add a message to the conversation."""
        self.messages.append(
            ConversationMessage(
                role=role,
                content=content,
                tool_used=tool_used,
                metadata=metadata,
            )
        )

    def get_recent_messages(self, count: int = 10) -> list[ConversationMessage]:
        """Get the most recent messages."""
        return self.messages[-count:] if self.messages else []


# =============================================================================
# API REQUEST/RESPONSE MODELS
# =============================================================================


class ChatRequest(BaseModel):
    """Request model for chat endpoint."""

    message: str = Field(..., min_length=1, max_length=10000, description="User message")
    source: str = Field(default="api", description="Source: api, text, voice")
    session_id: str | None = Field(
        default=None, description="Session ID for conversation continuity"
    )
    request_id: str | None = Field(default=None, description="Optional request ID for tracing")

    model_config = {
        "json_schema_extra": {
            "example": {
                "message": "What is the weather like today?",
                "source": "api",
                "session_id": "session_12345",
            }
        }
    }


class ChatResponse(BaseModel):
    """Response model for chat endpoint."""

    response: str = Field(..., description="Assistant's response")
    source: str = Field(..., description="Request source")
    session_id: str = Field(..., description="Session ID for this conversation")
    tools_used: list[str] = Field(default_factory=list, description="Tools that were used")

    model_config = {
        "json_schema_extra": {
            "example": {
                "response": "The weather is sunny and 25 degrees.",
                "source": "api",
                "session_id": "session_12345",
                "tools_used": ["get_weather"],
            }
        }
    }


class ToolListResponse(BaseModel):
    """Response model for tool listing."""

    total: int
    categories: dict[str, list[str]]


class MessageResponse(BaseModel):
    """Single message in history."""

    role: str
    content: str
    tool_used: str | None = None
    timestamp: str | None = None


class HistoryResponse(BaseModel):
    """Response model for conversation history."""

    session_id: str
    messages: list[MessageResponse]
    total: int


class HealthResponse(BaseModel):
    """Detailed health check response."""

    status: str
    service: str
    version: str
    environment: str
    database: str
    voice_enabled: bool
    classifier_enabled: bool
    cache_stats: dict | None = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "healthy",
                "service": "Amadeus",
                "version": "2.0.0",
                "environment": "production",
                "database": "connected",
                "voice_enabled": True,
                "classifier_enabled": True,
            }
        }
    }


class SystemStatusResponse(BaseModel):
    """System status response."""

    cpu_usage: float
    memory_usage: float
    disk_usage: float
    battery_percent: float | None
    is_charging: bool
    uptime_seconds: float
    is_healthy: bool
    alerts: list[str]

    model_config = {
        "json_schema_extra": {
            "example": {
                "cpu_usage": 15.2,
                "memory_usage": 45.1,
                "disk_usage": 60.5,
                "battery_percent": 95.0,
                "is_charging": True,
                "uptime_seconds": 3600.5,
                "is_healthy": True,
                "alerts": [],
            }
        }
    }


class TaskCreate(BaseModel):
    """Schema for creating a task."""

    content: str = Field(..., min_length=1, max_length=1000, description="Task content")

    model_config = {"json_schema_extra": {"example": {"content": "Buy groceries for the week"}}}


class TaskResponse(BaseModel):
    """Schema for task response."""

    id: int
    content: str
    status: str
    created_at: str
    completed_at: str | None = None

    @classmethod
    def from_domain(cls, task: Task) -> "TaskResponse":
        if task.id is None:
            raise ValueError("Cannot convert unsaved Task to TaskResponse")
        return cls(
            id=task.id,
            content=task.content,
            status=task.status.value,
            created_at=task.created_at.isoformat(),
            completed_at=task.completed_at.isoformat() if task.completed_at else None,
        )

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 1,
                "content": "Buy groceries for the week",
                "status": "pending",
                "created_at": "2023-11-20T10:00:00Z",
                "completed_at": None,
            }
        }
    }


class TaskListResponse(BaseModel):
    """Schema for task list response."""

    tasks: list[TaskResponse]
    total: int
    pending: int
    completed: int

    model_config = {
        "json_schema_extra": {"example": {"tasks": [], "total": 0, "pending": 0, "completed": 0}}
    }
