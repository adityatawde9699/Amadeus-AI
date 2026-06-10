"""
Cognitive Core Domain Models for Amadeus AI.

These models define the explicit data structures for autonomous planning
and execution. By using explicit state rather than ReAct scratchpads,
the system can pause, audit, resume, and recover.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PlanStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"

class ExecutionState(StrEnum):
    RECEIVED = "RECEIVED"
    CONTEXTUALIZING = "CONTEXTUALIZING"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    REFLECTING = "REFLECTING"
    MEMORY_COMMIT = "MEMORY_COMMIT"
    DONE = "DONE"
    BLOCKED = "BLOCKED"

class Observation(BaseModel):
    """Result from a tool, model, or external event."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: str  # e.g., tool name
    content: str
    success: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

class Reflection(BaseModel):
    """Post-step evaluation with confidence and next action."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    step_id: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    analysis: str
    suggested_action: str | None = None
    is_dead_end: bool = False

class PlanStep(BaseModel):
    """Atomic executable unit in a plan."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str
    tool: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING
    dependencies: list[str] = Field(default_factory=list)  # List of step IDs
    risk_level: str = "low"
    max_retries: int = 3
    retry_count: int = 0
    observations: list[Observation] = Field(default_factory=list)
    reflection: Reflection | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

class Plan(BaseModel):
    """Versioned decomposition of a goal or task."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    goal_id: str | None = None
    request_id: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    original_task: str
    status: PlanStatus = PlanStatus.DRAFT
    version: int = 1
    steps: list[PlanStep] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def get_ready_steps(self) -> list[PlanStep]:
        """Return steps that are pending and have all dependencies completed."""
        completed_ids = {s.id for s in self.steps if s.status == StepStatus.COMPLETED}
        ready = []
        for step in self.steps:
            if step.status == StepStatus.PENDING:
                if all(dep in completed_ids for dep in step.dependencies):
                    ready.append(step)
        return ready

class CognitiveContext(BaseModel):
    """Execution context for the CognitiveCore."""
    request_id: str
    session_id: str
    user_id: str
    state: ExecutionState = ExecutionState.RECEIVED
    plan: Plan | None = None
    final_output: str | None = None
    history: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
