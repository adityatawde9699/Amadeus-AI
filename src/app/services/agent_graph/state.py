"""Graph state, results and the queue-full error shared by the agent graph."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Annotated, TypedDict


logger = logging.getLogger(__name__)


# =============================================================================
# EXCEPTIONS (backward compat — imported by routes/chat.py, telegram_transport)
# =============================================================================


class QueueFullError(Exception):
    """Raised when the system cannot accept new requests."""


# =============================================================================
# STATE SCHEMA
# =============================================================================


def _merge_lists(left: list, right: list) -> list:
    """Reducer for list state fields: append right to left."""
    return left + right


class AmadeusState(TypedDict, total=False):
    """LangGraph state schema for the Amadeus MoE agent graph."""

    task: str
    plan: str
    observations: Annotated[list[str], _merge_lists]
    tools_used: Annotated[list[str], _merge_lists]
    final_answer: str
    requires_hitl: bool
    hitl_request_id: str
    permission_profile: str
    session_id: str
    iteration: int
    max_iterations: int
    # Cycle-detection: serialized action signatures seen so far
    seen_signatures: Annotated[list[str], _merge_lists]
    # Intermediate: current tool + args chosen by the planner
    current_tool: str
    current_args: dict
    # Flag for conditional edge
    should_continue: bool
    # Error tracking
    error: str
    # MoE: The active expert profile name (set by supervisor)
    active_expert: str
    # MoE: Pre-computed routing intent from semantic router
    routing_intent: str   # 'expert', 'tool', 'conversational', 'cloud_escalation'
    routing_target: str   # expert_name or tool_name
    # Orchestration (multi-expert chaining). When `orchestrated` is True, the
    # orchestrator has decomposed the request into `plan_steps`, each dispatched
    # to a specialized expert in sequence; otherwise the single-expert path runs.
    orchestrated: bool
    plan_steps: list[dict]        # [{"expert": str, "subtask": str}]
    current_step: int
    step_results: Annotated[list[str], _merge_lists]
    root_task: str                # original request, preserved across steps
    allow_orchestration: bool
    max_sub_agents: int
    # Phase 4 — in-graph HITL gate for risky tools
    allow_hitl: bool
    # True once a tool that returns external/attacker-influenced content (web,
    # news, email, MCP, ...) has run in this task. Taint gate: afterwards every
    # state-changing tool needs explicit human approval.
    untrusted_context: bool


# =============================================================================
# RESULT DATACLASS (backward compat)
# =============================================================================


@dataclass
class AgentResult:
    """Final result from agent execution."""

    success: bool
    final_answer: str
    steps: list[dict] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    total_iterations: int = 0
    error: str | None = None
    plan: str | None = None
    expert_used: str | None = None
    # Phase 4 — in-graph human-in-the-loop. When the graph pauses on a risky
    # tool, the run returns with requires_hitl=True; the caller approves/denies
    # and resumes via AmadeusGraph.aresume(hitl_request_id, approved).
    requires_hitl: bool = False
    hitl_request_id: str | None = None
    hitl_payload: dict | None = None


# =============================================================================
# LEGACY BACKWARD COMPATIBILITY
# =============================================================================
# The following classes are preserved for backward compatibility with existing
# tests and import paths. They are NOT used in the v5 execution path.


@dataclass
class AgentStep:
    """Single step in the agent's reasoning process (legacy)."""

    step_number: int
    thought: str
    action: str | None = None
    action_input: dict = field(default_factory=dict)
    observation: str | None = None
    plan_update: str | None = None

    def to_prompt(self) -> str:
        lines = [f"Step {self.step_number}:"]
        lines.append(f"Thought: {self.thought}")
        if self.action:
            lines.append(f"Action: {self.action}")
        if self.observation:
            lines.append(f"Observation: {self.observation}")
        return "\n".join(lines)
