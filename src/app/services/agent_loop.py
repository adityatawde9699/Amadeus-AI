"""
LangGraph Agent Loop for Amadeus AI v5 — Agentic MoE Architecture.

Replaces the monolithic single-agent graph with a Mixture-of-Experts (MoE)
Supervisor pattern. Each Expert Node runs its own Plan-and-Solve loop with
a constrained tool subset.

Graph shape:
  supervisor_node → expert_node(profile) → plan_node → tool_node → reflect_node
                                                                      ↓
                                                              synthesize_node → END

The Supervisor is lightweight — it reads the pre-computed routing intent from
the graph state and transitions to the correct Expert. Each Expert runs a
full Plan → Tool → Reflect → Synthesize loop internally, but ONLY with its
own tools.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command

from src.core.domain.agent_profiles import (
    AGENT_PROFILES,
    AgentProfile,
)


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langchain_core.runnables import RunnableConfig
    from langgraph.graph.state import CompiledStateGraph

    from src.app.services.tool_registry import ToolRegistry
    from src.core.domain.context import RequestContext
    from src.infra.tools.base import ToolExecutor

logger = logging.getLogger(__name__)

from src.app.services.agent_graph.expert import ExpertNodes
from src.app.services.agent_graph.orchestration import OrchestrationNodes
from src.app.services.agent_graph.state import (
    AgentResult,
    AgentStep,
    AmadeusState,
    QueueFullError,
)


__all__ = ["AgentResult", "AgentStep", "AmadeusGraph", "AmadeusState", "QueueFullError"]


class AmadeusGraph(OrchestrationNodes, ExpertNodes):
    """
    LangGraph StateGraph-based MoE agent for Amadeus AI.

    Architecture:
        supervisor_node → expert_plan_node → expert_tool_node → expert_reflect_node
                                                                    ↓
                                                            synthesize_node → END

    The Supervisor reads the routing intent from state and sets the active
    expert profile. The expert nodes use Plan-and-Solve with a constrained
    tool subset.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
        llm_generate: Callable[..., Awaitable[str]] | None = None,
        max_iterations: int = 5,
        checkpointer: Any | None = None,
        memory_service: Any | None = None,
    ) -> None:
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor
        self.llm_generate = llm_generate
        self._llm_accepts_schema = self._accepts_kwarg(llm_generate, "json_schema")
        self.default_max_iterations = max_iterations
        self.memory_service = memory_service

        # Build checkpointer (in-memory by default; replaced by AsyncSqliteSaver in initialize())
        self._checkpointer = checkpointer or MemorySaver()

        # Pre-build profile lookup for fast access
        self._profiles: dict[str, AgentProfile] = {p.name: p for p in AGENT_PROFILES}

        # Compile the graph
        self._graph: CompiledStateGraph = self._build_graph()
        logger.info(
            "AmadeusGraph MoE compiled (experts=%d, max_iter=%d)",
            len(self._profiles),
            max_iterations,
        )

    def set_checkpointer(self, checkpointer: Any) -> None:
        """Hot-swap the checkpointer and recompile the graph.

        Called by AmadeusService.initialize() once AsyncSqliteSaver is open.
        """
        self._checkpointer = checkpointer
        self._graph = self._build_graph()
        logger.info("AmadeusGraph recompiled with AsyncSqliteSaver checkpointer")

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def _build_graph(self) -> CompiledStateGraph:
        """Build and compile the MoE LangGraph StateGraph."""
        builder = StateGraph(AmadeusState)

        # Register nodes
        builder.add_node("orchestrator_node", self._orchestrator_node)
        builder.add_node("supervisor_node", self._supervisor_node)
        builder.add_node("expert_plan_node", self._expert_plan_node)
        builder.add_node("expert_tool_node", self._expert_tool_node)
        builder.add_node("expert_reflect_node", self._expert_reflect_node)
        builder.add_node("collect_step_node", self._collect_step_node)
        builder.add_node("synthesize_node", self._synthesize_node)

        # Entry point — Orchestrator decomposes (multi-expert) or passes through
        builder.set_entry_point("orchestrator_node")

        # Orchestrator → Supervisor (always; supervisor reads the current step)
        builder.add_edge("orchestrator_node", "supervisor_node")

        # Supervisor → Expert Plan (always)
        builder.add_edge("supervisor_node", "expert_plan_node")

        # Expert Plan → Expert Tool
        builder.add_edge("expert_plan_node", "expert_tool_node")

        # Expert Tool → Reflect, or this expert is done (collect its result)
        builder.add_conditional_edges(
            "expert_tool_node",
            self._after_tool_router,
            {
                "reflect": "expert_reflect_node",
                "collect": "collect_step_node",
            },
        )

        # Reflect → Continue looping or this expert is done
        builder.add_conditional_edges(
            "expert_reflect_node",
            self._should_continue_router,
            {
                "continue": "expert_tool_node",
                "finish": "collect_step_node",
            },
        )

        # Collect → next expert step (back to supervisor) or final synthesis
        builder.add_conditional_edges(
            "collect_step_node",
            self._collect_router,
            {
                "next_step": "supervisor_node",
                "synthesize": "synthesize_node",
            },
        )

        builder.add_edge("synthesize_node", END)

        return builder.compile(checkpointer=self._checkpointer)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def ainvoke(
        self,
        task: str,
        context: RequestContext,
        context_summary: str = "",
        max_iterations: int | None = None,
        routing_intent: str = "conversational",
        routing_target: str = "",
        allow_orchestration: bool | None = None,
    ) -> AgentResult:
        """
        Execute a task through the MoE LangGraph agent.

        Drop-in replacement for the legacy AmadeusGraph.ainvoke().

        Args:
            task: The user's input/task.
            context: RequestContext with session, user, permissions.
            context_summary: Conversation context for the LLM.
            max_iterations: Override for max iterations (expert default used if None).
            routing_intent: Pre-computed intent from semantic router.
            routing_target: Expert name or tool name from semantic router.
            allow_orchestration: Force multi-expert orchestration on/off. When
                None, derived from the host capability tier (Lite = off).
        """
        thread_id = context.session_id or str(uuid.uuid4())
        max_iter = max_iterations or self.default_max_iterations

        # Resolve orchestration budget from the hardware capability tier.
        from src.core.config import get_settings

        settings = get_settings()
        capability = settings.capability
        if allow_orchestration is None:
            allow_orchestration = capability.allow_orchestration
        max_sub_agents = capability.max_sub_agents
        allow_hitl = bool(getattr(settings, "ENABLE_INGRAPH_HITL", False))

        initial_state: dict[str, Any] = {
            "task": task,
            "plan": "",
            "observations": [],
            "tools_used": [],
            "final_answer": "",
            "requires_hitl": False,
            "hitl_request_id": "",
            "permission_profile": context.permissions.name,
            "session_id": context.session_id,
            "iteration": 0,
            "max_iterations": max_iter,
            "seen_signatures": [],
            "current_tool": "",
            "current_args": {},
            "should_continue": True,
            "error": "",
            # MoE fields
            "active_expert": "",
            "routing_intent": routing_intent,
            "routing_target": routing_target,
            # Orchestration fields
            "orchestrated": False,
            "plan_steps": [],
            "current_step": 0,
            "step_results": [],
            "root_task": task,
            "allow_orchestration": bool(allow_orchestration),
            "max_sub_agents": max_sub_agents,
            "allow_hitl": allow_hitl,
            "untrusted_context": False,
        }

        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

        try:
            final_state = await self._graph.ainvoke(initial_state, config=config)
            return await self._result_from_state(final_state, thread_id, context)
        except Exception as e:
            logger.exception("MoE LangGraph execution failed: %s", e)
            return AgentResult(
                success=False,
                final_answer=f"I encountered an error while processing your request: {e}",
                error=str(e),
            )

    async def aresume(self, hitl_request_id: str, approved: bool) -> AgentResult:
        """Resume a graph paused on an in-graph HITL approval (Phase 4).

        ``hitl_request_id`` is the ``thread_id`` returned in the paused
        AgentResult. The graph re-enters the interrupted tool node, ``interrupt()``
        returns ``approved``, and execution continues (and may pause again on a
        further risky step).
        """
        config: RunnableConfig = {"configurable": {"thread_id": hitl_request_id}}
        try:
            final_state = await self._graph.ainvoke(Command(resume=approved), config=config)
            return await self._result_from_state(final_state, hitl_request_id, None)
        except Exception as e:
            logger.exception("HITL resume failed: %s", e)
            return AgentResult(
                success=False,
                final_answer=f"Failed to resume the paused task: {e}",
                error=str(e),
            )

    async def _result_from_state(
        self, final_state: dict, thread_id: str, context: RequestContext | None
    ) -> AgentResult:
        """Build an AgentResult, surfacing interrupts and recording outcomes."""
        # Graph paused for human approval — surface it to the caller.
        interrupts = final_state.get("__interrupt__")
        if interrupts:
            payload = self._interrupt_payload(interrupts)
            return AgentResult(
                success=False,
                final_answer=payload.get("question", "Approval required to continue."),
                requires_hitl=True,
                hitl_request_id=thread_id,
                hitl_payload=payload,
                expert_used=final_state.get("active_expert"),
            )

        result = AgentResult(
            success=bool(final_state.get("final_answer")),
            final_answer=final_state.get("final_answer", ""),
            tools_used=final_state.get("tools_used", []),
            total_iterations=final_state.get("iteration", 0),
            plan=final_state.get("plan"),
            expert_used=final_state.get("active_expert"),
        )

        # Phase 4: reflective learning — record this run's tool outcomes so
        # future plans can learn from past successes/failures.
        if context is not None:
            await self._record_outcomes(final_state, context)
        return result

    async def shutdown(self) -> None:
        """Clean up the graph. Checkpointer lifecycle is managed by AmadeusService."""
        logger.info("AmadeusGraph MoE shut down cleanly")
