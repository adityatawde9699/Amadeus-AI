"""
LangGraph Agent Loop for Amadeus AI v5.

Replaces the legacy ReActAgent + AgentOrchestrator with a LangGraph
StateGraph that provides:
  - Typed state schema (AmadeusState)
  - Checkpointed crash recovery via SqliteSaver
  - Cycle-detection guard (preserved from legacy)
  - Drop-in compatibility with AmadeusService._process_with_agent()

Graph shape:
  plan_node → tool_node → reflect_node ─┬→ tool_node (loop)
                                         └→ synthesize_node → END
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.app.services.tool_registry import ToolRegistry
from src.core.domain.context import RequestContext
from src.core.domain.models import PermissionProfile
from src.infra.tools.base import ToolExecutor


if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

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
    """LangGraph state schema for the Amadeus agent graph."""

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


# =============================================================================
# LANGGRAPH AGENT GRAPH
# =============================================================================


class AmadeusGraph:
    """
    LangGraph StateGraph-based agent for Amadeus AI.

    Replaces the legacy ReActAgent + AgentOrchestrator.
    Nodes: plan → tool → reflect → (loop or synthesize)
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
        self.default_max_iterations = max_iterations
        self.memory_service = memory_service

        # Build checkpointer (in-memory by default, can be swapped for SqliteSaver)
        self._checkpointer = checkpointer or MemorySaver()

        # Compile the graph
        self._graph: CompiledStateGraph = self._build_graph()
        logger.info("AmadeusGraph compiled (max_iter=%d)", max_iterations)

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def _build_graph(self) -> CompiledStateGraph:
        """Build and compile the LangGraph StateGraph."""
        builder = StateGraph(AmadeusState)  # type: ignore

        # Register nodes
        builder.add_node("plan_node", self._plan_node)
        builder.add_node("tool_node", self._tool_node)
        builder.add_node("reflect_node", self._reflect_node)
        builder.add_node("synthesize_node", self._synthesize_node)

        # Entry point
        builder.set_entry_point("plan_node")

        # Edges
        builder.add_edge("plan_node", "tool_node")
        builder.add_conditional_edges(
            "tool_node",
            self._after_tool_router,
            {
                "reflect": "reflect_node",
                "synthesize": "synthesize_node",
            },
        )
        builder.add_conditional_edges(
            "reflect_node",
            self._should_continue_router,
            {
                "continue": "tool_node",
                "finish": "synthesize_node",
            },
        )
        builder.add_edge("synthesize_node", END)

        return builder.compile(checkpointer=self._checkpointer)

    # ------------------------------------------------------------------
    # Node implementations
    # ------------------------------------------------------------------

    async def _plan_node(self, state: AmadeusState) -> dict:
        """Decompose the task into a plan and decide the first tool call."""
        task = state.get("task", "")
        max_iter = state.get("max_iterations", self.default_max_iterations)

        # Build plan via LLM
        plan = "No plan (keyword mode)"
        first_tool = ""
        first_args: dict = {}

        if self.llm_generate:
            tool_menu = self.tool_registry.get_tools_menu()

            # Retrieve semantic memories if available
            memory_block = ""
            if self.memory_service is not None:
                try:
                    memories = await self.memory_service.retrieve(task, top_k=3)
                    if memories:
                        formatted = self.memory_service.format_for_prompt(memories)
                        if formatted:
                            memory_block = f"\n[RETRIEVED MEMORIES]\n{formatted}\n"
                except Exception:
                    pass

            json_template = """{
  "plan": "step-by-step plan",
  "tool": "first_tool_name or FINISH",
  "args": {"param": "value"},
  "intent": "your reasoning"
}"""
            prompt = f"""You are Amadeus — an advanced autonomous AI agent.

Task: {task}
{memory_block}

Available Tools:
{tool_menu}
- FINISH: Use when task is complete. Input: {{"answer": "your final response"}}

Create a plan and decide the FIRST action. Respond with JSON only:
{json_template}"""
            try:
                response = await self.llm_generate(prompt, structured=True)
                parsed = self._parse_json_response(response)
                plan = parsed.get("plan", plan)
                first_tool = parsed.get("tool", "FINISH")
                first_args = parsed.get("args", {})
            except Exception as e:
                logger.warning("Plan node LLM failed: %s — falling back to keyword", e)
                first_tool, first_args = self._keyword_match(task, set())
        else:
            first_tool, first_args = self._keyword_match(task, set())

        updates: dict[str, Any] = {
            "plan": plan,
            "iteration": 1,
            "max_iterations": max_iter,
            "current_tool": first_tool,
            "current_args": first_args,
            "should_continue": first_tool != "FINISH",
        }

        if first_tool == "FINISH":
            updates["final_answer"] = first_args.get("answer", plan)

        return updates

    async def _tool_node(self, state: AmadeusState) -> dict:
        """Execute the current tool."""
        tool_name = state.get("current_tool", "")
        tool_args = state.get("current_args", {})
        permission_str = state.get("permission_profile", "READ_ONLY")

        # Resolve permission profile
        try:
            permission_profile = PermissionProfile[permission_str]
        except (KeyError, ValueError):
            permission_profile = PermissionProfile.READ_ONLY

        if not tool_name or tool_name == "FINISH":
            return {
                "observations": [f"FINISH: {tool_args.get('answer', 'Task complete')}"],
                "should_continue": False,
                "final_answer": tool_args.get("answer", ""),
            }

        tool = self.tool_registry.get(tool_name)
        if not tool:
            return {
                "observations": [f"Error: Tool '{tool_name}' not found in registry"],
                "should_continue": True,
            }

        try:
            result = await asyncio.wait_for(
                self.tool_executor.execute(
                    tool, tool_args, permission_profile=permission_profile,
                ),
                timeout=30,
            )
            observation = (
                str(result.result) if result.success else f"Error: {result.error_message}"
            )
            tool_used = [tool_name] if result.success else []
            return {
                "observations": [f"{tool_name}: {observation}"],
                "tools_used": tool_used,
                "should_continue": True,
            }
        except TimeoutError:
            return {
                "observations": [f"{tool_name}: Error — timed out after 30s"],
                "should_continue": True,
            }
        except Exception as e:
            return {
                "observations": [f"{tool_name}: Error — {e}"],
                "should_continue": True,
            }

    async def _reflect_node(self, state: AmadeusState) -> dict:
        """Observe the last result and decide the next action."""
        task = state.get("task", "")
        iteration = state.get("iteration", 1)
        max_iterations = state.get("max_iterations", self.default_max_iterations)
        observations = state.get("observations", [])
        plan = state.get("plan", "")
        seen_signatures = state.get("seen_signatures", [])

        # Max iterations check
        if iteration >= max_iterations:
            logger.info("Max iterations (%d) reached — synthesizing", max_iterations)
            return {"should_continue": False}

        next_tool = "FINISH"
        next_args: dict = {}

        if self.llm_generate:
            obs_text = "\n".join(f"  - {o}" for o in observations[-5:])
            json_template = """{
  "intent": "your reasoning",
  "tool": "next_tool_name or FINISH",
  "args": {"param": "value"}
}"""
            prompt = f"""You are Amadeus — an advanced autonomous AI agent.

Plan: {plan}
Task: {task}

Previous observations:
{obs_text}

Iteration: {iteration}/{max_iterations}

Decide the next action. If the task is complete, use FINISH.
Respond with JSON only:
{json_template}"""
            try:
                response = await self.llm_generate(prompt, structured=True)
                parsed = self._parse_json_response(response)
                next_tool = parsed.get("tool", "FINISH")
                next_args = parsed.get("args", {})
            except Exception as e:
                logger.warning("Reflect node LLM failed: %s — finishing", e)
                next_tool = "FINISH"
                next_args = {"answer": " ".join(
                    o.split(":", 1)[-1].strip() for o in observations if ":" in o
                )}
        else:
            done_tools = {o.split(":")[0] for o in observations}
            next_tool, next_args = self._keyword_match(task, done_tools)

        # Cycle detection
        if next_tool != "FINISH":
            sig = self._action_signature(next_tool, next_args)
            if sig in seen_signatures:
                logger.warning("Cycle detected for '%s' — forcing finish", next_tool)
                return {"should_continue": False}
            return {
                "current_tool": next_tool,
                "current_args": next_args,
                "iteration": iteration + 1,
                "seen_signatures": [sig],
                "should_continue": True,
            }

        # FINISH
        final = next_args.get("answer", "")
        if not final and observations:
            final = " ".join(
                o.split(":", 1)[-1].strip() for o in observations if ":" in o
            )

        return {
            "current_tool": "FINISH",
            "current_args": next_args,
            "should_continue": False,
            "final_answer": final,
        }

    async def _synthesize_node(self, state: AmadeusState) -> dict:
        """Combine all observations into a final answer."""
        observations = state.get("observations", [])
        final = state.get("final_answer", "")

        if final:
            return {"final_answer": final}

        if not observations:
            return {"final_answer": "I couldn't find relevant information for your request."}

        # Combine observations
        parts = []
        for obs in observations:
            if ":" in obs:
                _tool, result = obs.split(":", 1)
                result = result.strip()
                if result and not result.lower().startswith("error"):
                    parts.append(result)

        if not parts:
            return {"final_answer": "I encountered errors while processing your request."}

        return {"final_answer": " ".join(parts)}

    # ------------------------------------------------------------------
    # Conditional edge routers
    # ------------------------------------------------------------------

    def _after_tool_router(self, state: AmadeusState) -> Literal["reflect", "synthesize"]:
        """After tool execution: reflect if continuing, synthesize if done."""
        if not state.get("should_continue", True):
            return "synthesize"
        return "reflect"

    def _should_continue_router(self, state: AmadeusState) -> Literal["continue", "finish"]:
        """After reflection: continue looping or finish."""
        if state.get("should_continue", False):
            return "continue"
        return "finish"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def ainvoke(
        self,
        task: str,
        context: RequestContext,
        context_summary: str = "",
        max_iterations: int | None = None,
    ) -> AgentResult:
        """
        Execute a task through the LangGraph agent.

        Drop-in replacement for the legacy AgentOrchestrator.execute().
        """
        thread_id = context.session_id or str(uuid.uuid4())
        max_iter = max_iterations or self.default_max_iterations

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
        }

        config = {"configurable": {"thread_id": thread_id}}

        try:
            final_state = await self._graph.ainvoke(initial_state, config=config)

            return AgentResult(
                success=bool(final_state.get("final_answer")),
                final_answer=final_state.get("final_answer", ""),
                tools_used=final_state.get("tools_used", []),
                total_iterations=final_state.get("iteration", 0),
                plan=final_state.get("plan"),
            )
        except Exception as e:
            logger.exception("LangGraph execution failed: %s", e)
            return AgentResult(
                success=False,
                final_answer=f"I encountered an error while processing your request: {e}",
                error=str(e),
            )

    async def shutdown(self) -> None:
        """Clean up the checkpointer."""
        if hasattr(self._checkpointer, "conn") and self._checkpointer.conn:
            with contextlib.suppress(Exception):
                await self._checkpointer.conn.close()
        logger.info("AmadeusGraph shut down cleanly")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _keyword_match(self, task: str, done_tools: set[str]) -> tuple[str, dict]:
        """Simple keyword-based tool selection fallback."""
        task_lower = task.lower()

        intents = [
            (["time", "what time", "current time"], "get_datetime_info", {"query": "time"}),
            (["date", "what day", "today"], "get_datetime_info", {"query": "date"}),
            (["joke", "make me laugh", "funny"], "tell_joke", {}),
            (["system", "cpu", "memory", "status"], "system_status", {}),
            (["task", "tasks", "todo"], "list_tasks", {}),
            (["note", "notes"], "list_notes", {}),
            (["reminder", "reminders"], "list_reminders", {}),
            (["battery"], "get_battery_info", {}),
            (["news", "headlines"], "get_news", {}),
            (["email", "emails", "inbox"], "read_unread_emails", {}),
            (["weather"], "get_weather", {}),
        ]

        for keywords, tool_name, tool_input in intents:
            if tool_name in done_tools:
                continue
            if any(kw in task_lower for kw in keywords):
                if tool_name in self.tool_registry.list_names():
                    return tool_name, tool_input

        # All matched or nothing matched
        if done_tools:
            combined = "; ".join(done_tools)
            return "FINISH", {"answer": combined}

        return "FINISH", {
            "answer": "I'm not sure how to help with that. Try asking about time, weather, tasks, or system status."
        }

    @staticmethod
    def _action_signature(action: str, action_input: dict) -> str:
        """Build a stable, order-independent key for cycle detection."""
        normalized = json.dumps(action_input, sort_keys=True, default=str)
        return f"{action}|{normalized}"

    @staticmethod
    def _parse_json_response(response: str) -> dict:
        """Parse JSON from LLM response, handling markdown code fences."""
        cleaned = response.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        # Try to find JSON object in the response
        import re
        json_match = re.search(r"\{[^{}]*\}", cleaned, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        logger.warning("Failed to parse JSON from LLM response: %s", cleaned[:200])
        return {}


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
