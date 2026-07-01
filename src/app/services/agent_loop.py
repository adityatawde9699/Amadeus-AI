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

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from src.core.domain.agent_profiles import (
    AGENT_PROFILES,
    AgentProfile,
)
from src.core.domain.models import PermissionProfile


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langgraph.graph.state import CompiledStateGraph

    from src.app.services.tool_registry import ToolRegistry
    from src.core.domain.context import RequestContext
    from src.infra.tools.base import ToolExecutor

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
# LANGGRAPH MOE AGENT GRAPH
# =============================================================================


class AmadeusGraph:
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
        self.default_max_iterations = max_iterations
        self.memory_service = memory_service

        # Build checkpointer (in-memory by default; replaced by AsyncSqliteSaver in initialize())
        self._checkpointer = checkpointer or MemorySaver()

        # Pre-build profile lookup for fast access
        self._profiles: dict[str, AgentProfile] = {
            p.name: p for p in AGENT_PROFILES
        }

        # Compile the graph
        self._graph: CompiledStateGraph = self._build_graph()
        logger.info(
            "AmadeusGraph MoE compiled (experts=%d, max_iter=%d)",
            len(self._profiles), max_iterations,
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
        builder = StateGraph(AmadeusState)  # type: ignore

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
    # Orchestrator Node — multi-expert decomposition (tier-gated)
    # ------------------------------------------------------------------

    async def _orchestrator_node(self, state: AmadeusState) -> dict:
        """Decompose a multi-step request into a sequence of expert steps.

        Tier-gated: when orchestration is disabled (Lite tier) or the request is
        single-step, this is a cheap pass-through — `orchestrated` stays False and
        the existing single-expert routing path runs unchanged (no extra LLM call
        on the Lite tier, so the 4GB floor keeps its current latency).
        """
        task = state.get("task", "")
        allow = state.get("allow_orchestration", False)
        max_sub_agents = max(1, int(state.get("max_sub_agents", 1)))

        passthrough = {"orchestrated": False, "plan_steps": [], "current_step": 0,
                       "root_task": task}

        if not allow or max_sub_agents < 2 or not self.llm_generate:
            return passthrough

        steps = await self._decompose(task, max_sub_agents)
        if len(steps) < 2:
            # Single-step: defer to the existing semantic routing for best accuracy.
            return passthrough

        logger.info(
            "Orchestrator: decomposed into %d expert step(s): %s",
            len(steps), " → ".join(s["expert"] for s in steps),
        )
        return {
            "orchestrated": True,
            "plan_steps": steps,
            "current_step": 0,
            "root_task": task,
        }

    async def _decompose(self, task: str, max_steps: int) -> list[dict]:
        """Ask the LLM to split `task` into ordered (expert, subtask) steps."""
        expert_menu = "\n".join(
            f"- {p.name}: {p.description}"
            for p in AGENT_PROFILES if p.name != "generalist"
        )
        json_template = (
            '{\n  "steps": [\n    {"expert": "expert_name", "subtask": "what to do"}\n  ]\n}'
        )
        prompt = f"""You are the Orchestrator of Amadeus AI. Decompose the user's request \
into an ordered list of steps, each handled by ONE specialized expert. Keep the \
list as short as possible: if a single expert can satisfy the whole request, \
return exactly ONE step. Use at most {max_steps} steps. Only use experts from \
this list:

{expert_menu}

User request: {task}

Respond with JSON only:
{json_template}"""
        try:
            response = await self.llm_generate(prompt, structured=True)
            parsed = self._parse_json_response(response)
            raw_steps = parsed.get("steps", []) if isinstance(parsed, dict) else []
        except Exception as e:
            logger.warning("Orchestrator decomposition failed: %s — single-expert path", e)
            return []

        steps: list[dict] = []
        for item in raw_steps:
            if not isinstance(item, dict):
                continue
            expert = str(item.get("expert", "")).strip()
            subtask = str(item.get("subtask", "")).strip()
            if not subtask:
                continue
            if expert not in self._profiles:
                expert = "generalist"
            steps.append({"expert": expert, "subtask": subtask})
            if len(steps) >= max_steps:
                break
        return steps

    # ------------------------------------------------------------------
    # Supervisor Node — MoE Gating
    # ------------------------------------------------------------------

    async def _supervisor_node(self, state: AmadeusState) -> dict:
        """Read the routing intent and activate the appropriate expert.

        This node is intentionally lightweight — no LLM call. The heavy
        routing was already done by the SemanticRouter before graph invocation.
        """
        routing_intent = state.get("routing_intent", "conversational")
        routing_target = state.get("routing_target", "")
        task = state.get("task", "")

        # ── Orchestrated path: activate the expert for the current step ──
        if state.get("orchestrated") and state.get("plan_steps"):
            plan_steps = state["plan_steps"]
            step_idx = state.get("current_step", 0)
            step = plan_steps[min(step_idx, len(plan_steps) - 1)]
            expert_name = step["expert"] if step["expert"] in self._profiles else "generalist"
            profile = self._profiles[expert_name]
            logger.info(
                "Orchestrator step %d/%d → Expert: %s",
                step_idx + 1, len(plan_steps), profile.display_name,
            )
            return {
                "active_expert": expert_name,
                "max_iterations": profile.max_iterations,
                # The expert works on its subtask, not the full request.
                "task": step["subtask"],
            }

        # Determine which expert to activate
        expert_name = "generalist"  # default fallback

        if routing_intent == "expert" and routing_target:
            if routing_target in self._profiles:
                expert_name = routing_target
            else:
                logger.warning(
                    "Supervisor: unknown expert '%s', falling back to generalist",
                    routing_target,
                )

        elif routing_intent == "tool" and routing_target:
            # Map tool → its owning expert via category
            tool = self.tool_registry.get(routing_target)
            if tool:
                from src.core.domain.agent_profiles import get_profile_for_category
                profile = get_profile_for_category(tool.category)
                expert_name = profile.name
            else:
                logger.warning(
                    "Supervisor: tool '%s' not found, falling back to generalist",
                    routing_target,
                )

        profile = self._profiles.get(expert_name, self._profiles["generalist"])
        max_iter = profile.max_iterations

        logger.info(
            "MoE Supervisor: '%s' → Expert: %s (%s)",
            task[:50], profile.display_name, expert_name,
        )

        return {
            "active_expert": expert_name,
            "max_iterations": max_iter,
        }

    # ------------------------------------------------------------------
    # Expert Plan Node — Plan-and-Solve with constrained tools
    # ------------------------------------------------------------------

    async def _expert_plan_node(self, state: AmadeusState) -> dict:
        """Decompose the task into a plan using only the expert's tools."""
        task = state.get("task", "")
        expert_name = state.get("active_expert", "generalist")
        max_iter = state.get("max_iterations", self.default_max_iterations)

        profile = self._profiles.get(expert_name, self._profiles["generalist"])

        # Build plan via LLM
        plan = "No plan (keyword mode)"
        first_tool = ""
        first_args: dict = {}

        # Get the expert's constrained tool menu
        if profile.categories:
            tool_menu = self.tool_registry.get_tools_menu_for_categories(
                list(profile.categories)
            )
        else:
            # Generalist gets all tools
            tool_menu = self.tool_registry.get_tools_menu()

        if self.llm_generate:
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

            # Phase 4: inject relevant past tool outcomes (reflective learning).
            outcome_block = await self._retrieve_outcomes(task)

            json_template = """{\n  "plan": "step-by-step plan",\n  "tool": "first_tool_name or FINISH",\n  "args": {"param": "value"},\n  "intent": "your reasoning"\n}"""
            prompt = f"""{profile.system_prompt_preamble}

Task: {task}
{memory_block}{outcome_block}

Available Tools (you may ONLY use these):
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
                # Guard: validate the chosen tool is actually registered
                if first_tool not in ("FINISH", "") and not self.tool_registry.get(first_tool):
                    logger.warning(
                        "Expert plan chose unregistered tool '%s' — falling back to keyword match",
                        first_tool,
                    )
                    first_tool, first_args = self._keyword_match(task, set(), profile)
            except Exception as e:
                logger.warning("Expert plan LLM failed: %s — falling back to keyword", e)
                first_tool, first_args = self._keyword_match(task, set(), profile)
        else:
            first_tool, first_args = self._keyword_match(task, set(), profile)

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

    # ------------------------------------------------------------------
    # Expert Tool Node — Execute within expert's scope
    # ------------------------------------------------------------------

    async def _expert_tool_node(self, state: AmadeusState) -> dict:
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

        # ── Phase 4: in-graph human-in-the-loop gate ──────────────────
        # Pause the graph on a risky tool and wait for an approval decision.
        # interrupt() suspends execution here; on resume the node re-runs from
        # the top and interrupt() returns the value passed to Command(resume=...).
        if state.get("allow_hitl") and self._needs_approval(tool):
            decision = interrupt(
                {
                    "type": "tool_approval",
                    "tool": tool_name,
                    "args": tool_args,
                    "risk_level": getattr(tool, "risk_level", "high"),
                    "question": (
                        f"Approve running '{tool_name}' with args {tool_args}? "
                        f"(risk: {getattr(tool, 'risk_level', 'high')})"
                    ),
                }
            )
            if not self._approval_granted(decision):
                logger.info("HITL: tool '%s' denied by user", tool_name)
                return {
                    "observations": [f"{tool_name}: Skipped — action denied by user."],
                    "should_continue": True,
                }

        try:
            from src.app.services.tool_dispatcher import ToolDispatcher
            timeout = ToolDispatcher.TOOL_TIMEOUTS.get(tool_name, ToolDispatcher.DEFAULT_TIMEOUT)
            result = await asyncio.wait_for(
                self.tool_executor.execute(
                    tool, tool_args,
                    permission_profile=permission_profile,
                    session_id=state.get("session_id"),
                ),
                timeout=timeout,
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

    # ------------------------------------------------------------------
    # Expert Reflect Node — Decide next action within expert scope
    # ------------------------------------------------------------------

    async def _expert_reflect_node(self, state: AmadeusState) -> dict:
        """Observe the last result and decide the next action."""
        task = state.get("task", "")
        iteration = state.get("iteration", 1)
        max_iterations = state.get("max_iterations", self.default_max_iterations)
        observations = state.get("observations", [])
        plan = state.get("plan", "")
        seen_signatures = state.get("seen_signatures", [])
        expert_name = state.get("active_expert", "generalist")

        profile = self._profiles.get(expert_name, self._profiles["generalist"])

        # Max iterations check
        if iteration >= max_iterations:
            logger.info("Max iterations (%d) reached for %s — synthesizing", max_iterations, expert_name)
            return {"should_continue": False}

        next_tool = "FINISH"
        next_args: dict = {}

        if self.llm_generate:
            obs_text = "\n".join(f"  - {o}" for o in observations[-5:])

            # Expert-constrained tool menu
            if profile.categories:
                tool_menu = self.tool_registry.get_tools_menu_for_categories(
                    list(profile.categories)
                )
            else:
                tool_menu = self.tool_registry.get_tools_menu()

            json_template = """{\n  "intent": "your reasoning",\n  "tool": "next_tool_name or FINISH",\n  "args": {"param": "value"}\n}"""
            prompt = f"""{profile.system_prompt_preamble}

Plan: {plan}
Task: {task}

Available Tools (you may ONLY use these):
{tool_menu}
- FINISH: Use when task is complete. Input: {{"answer": "your final response"}}

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
                # Guard: validate the chosen tool is actually registered
                if next_tool not in ("FINISH", "") and not self.tool_registry.get(next_tool):
                    logger.warning(
                        "Expert reflect chose unregistered tool '%s' — falling back to keyword match",
                        next_tool,
                    )
                    done = {o.split(":")[0] for o in observations}
                    next_tool, next_args = self._keyword_match(task, done, profile)
            except Exception as e:
                logger.warning("Expert reflect LLM failed: %s — finishing", e)
                next_tool = "FINISH"
                next_args = {"answer": " ".join(
                    o.split(":", 1)[-1].strip() for o in observations if ":" in o
                )}
        else:
            done_tools = {o.split(":")[0] for o in observations}
            next_tool, next_args = self._keyword_match(task, done_tools, profile)

        # Cycle detection (scoped per orchestrated step so the same tool reused
        # by a later expert step is not mistaken for a loop).
        if next_tool != "FINISH":
            step_scope = state.get("current_step", 0)
            sig = f"{step_scope}:{self._action_signature(next_tool, next_args)}"
            if sig in seen_signatures:
                logger.warning("Cycle detected for '%s' in %s — forcing finish", next_tool, expert_name)
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

    # ------------------------------------------------------------------
    # Collect Step Node — capture an expert's result, advance the plan
    # ------------------------------------------------------------------

    async def _collect_step_node(self, state: AmadeusState) -> dict:
        """Record the finished expert's result and advance to the next step.

        Non-orchestrated runs fall straight through to synthesis (the router
        sends them to `synthesize_node`), so single-expert behaviour is
        unchanged. In orchestrated mode we snapshot this expert's answer, then
        reset the per-step scratch so the next expert starts clean.
        """
        if not state.get("orchestrated"):
            return {}

        plan_steps = state.get("plan_steps", [])
        step_idx = state.get("current_step", 0)
        step = plan_steps[min(step_idx, len(plan_steps) - 1)] if plan_steps else {}
        expert = step.get("expert", "expert")

        # This step's result: the expert's final_answer, else its observations.
        result = state.get("final_answer", "")
        if not result:
            observations = state.get("observations", [])
            result = " ".join(
                o.split(":", 1)[-1].strip() for o in observations if ":" in o
            ).strip()
        result = result or "(no output)"

        return {
            "step_results": [f"[{expert}] {result}"],
            "current_step": step_idx + 1,
            # Reset per-step scratch so the next expert plans fresh.
            "final_answer": "",
            "current_tool": "",
            "current_args": {},
            "should_continue": True,
        }

    # ------------------------------------------------------------------
    # Synthesize Node — Final answer assembly
    # ------------------------------------------------------------------

    async def _synthesize_node(self, state: AmadeusState) -> dict:
        """Combine all observations into a final answer."""
        observations = state.get("observations", [])
        final = state.get("final_answer", "")

        # ── Orchestrated: merge the per-expert step results ──
        if state.get("orchestrated") and state.get("step_results"):
            return {"final_answer": await self._merge_step_results(state)}

        if final:
            return {"final_answer": final}

        if not observations:
            return {"final_answer": "I couldn't find relevant information for your request."}

        # Combine observations — filter out error and tool-not-found messages
        _ERROR_PREFIXES = (
            "error",
            "tool '",           # 'Tool 'x' not found in registry'
            "tool not found",
            "not found in registry",
        )
        parts = []
        for obs in observations:
            if ":" in obs:
                _tool, result = obs.split(":", 1)
                result = result.strip()
                if result and not result.lower().startswith(_ERROR_PREFIXES):
                    parts.append(result)

        if not parts:
            return {"final_answer": "I encountered errors while processing your request."}

        return {"final_answer": " ".join(parts)}

    async def _merge_step_results(self, state: AmadeusState) -> str:
        """Combine per-expert step results into one coherent answer."""
        root_task = state.get("root_task") or state.get("task", "")
        step_results = state.get("step_results", [])
        joined = "\n".join(step_results)

        if not self.llm_generate:
            # No LLM: return the concatenated expert outputs directly.
            return "\n".join(r.split("] ", 1)[-1] for r in step_results)

        prompt = f"""You are Amadeus AI. The user's request was handled by several \
specialized experts in sequence. Combine their results into a single, coherent \
response. Do not mention the experts or the internal steps.

User request: {root_task}

Expert results:
{joined}

Final response:"""
        try:
            return (await self.llm_generate(prompt)).strip() or joined
        except Exception as e:
            logger.warning("Step-result merge failed: %s — returning concatenation", e)
            return "\n".join(r.split("] ", 1)[-1] for r in step_results)

    # ------------------------------------------------------------------
    # Conditional edge routers
    # ------------------------------------------------------------------

    def _after_tool_router(self, state: AmadeusState) -> Literal["reflect", "collect"]:
        """After tool execution: reflect if continuing, else collect this step."""
        if not state.get("should_continue", True):
            return "collect"
        return "reflect"

    def _should_continue_router(self, state: AmadeusState) -> Literal["continue", "finish"]:
        """After reflection: continue looping or finish this expert step."""
        if state.get("should_continue", False):
            return "continue"
        return "finish"

    def _collect_router(self, state: AmadeusState) -> Literal["next_step", "synthesize"]:
        """After collecting a step: advance to the next expert or synthesize.

        `_collect_step_node` has already advanced `current_step`, so it now points
        at the next step to run (or past the end when the plan is exhausted).
        """
        if not state.get("orchestrated"):
            return "synthesize"
        if state.get("current_step", 0) < len(state.get("plan_steps", [])):
            return "next_step"
        return "synthesize"

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
        }

        config = {"configurable": {"thread_id": thread_id}}

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
        config = {"configurable": {"thread_id": hitl_request_id}}
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

    @staticmethod
    def _interrupt_payload(interrupts: Any) -> dict:
        """Extract the value dict from LangGraph's __interrupt__ structure."""
        try:
            first = interrupts[0] if isinstance(interrupts, (list, tuple)) else interrupts
            value = getattr(first, "value", first)
            return value if isinstance(value, dict) else {"question": str(value)}
        except Exception:
            return {"question": "Approval required to continue."}

    async def shutdown(self) -> None:
        """Clean up the graph. Checkpointer lifecycle is managed by AmadeusService."""
        logger.info("AmadeusGraph MoE shut down cleanly")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _keyword_match(
        self, task: str, done_tools: set[str], profile: AgentProfile | None = None
    ) -> tuple[str, dict]:
        """Simple keyword-based tool selection fallback, scoped to expert."""
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
            (["bitcoin", "btc"], "get_crypto_price", {"coin": "bitcoin"}),
            (["ethereum", "eth"], "get_crypto_price", {"coin": "ethereum"}),
            (["search", "look up", "google"], "web_search", {"query": task}),
        ]

        # If scoped to an expert, only consider tools in its categories
        if profile and profile.categories:
            allowed_tools = {
                t.name for t in self.tool_registry.get_tools_by_categories(
                    list(profile.categories)
                )
            }
        else:
            allowed_tools = set(self.tool_registry.list_names())

        for keywords, tool_name, tool_input in intents:
            if tool_name in done_tools:
                continue
            if tool_name not in allowed_tools:
                continue
            if any(kw in task_lower for kw in keywords) and tool_name in self.tool_registry.list_names():
                return tool_name, tool_input

        # All matched or nothing matched
        if done_tools:
            combined = "; ".join(done_tools)
            return "FINISH", {"answer": combined}

        return "FINISH", {
            "answer": "I'm not sure how to help with that. Try asking about time, weather, tasks, or system status."
        }

    # ------------------------------------------------------------------
    # Phase 4 — reflective learning
    # ------------------------------------------------------------------

    async def _record_outcomes(self, final_state: dict, context: RequestContext) -> None:
        """Persist compact per-tool outcome records for future planning."""
        if self.memory_service is None or not getattr(self.memory_service, "is_enabled", False):
            return
        from src.core.config import get_settings

        if not getattr(get_settings(), "ENABLE_REFLECTIVE_LEARNING", True):
            return

        task = (final_state.get("root_task") or final_state.get("task") or "").strip()
        observations = final_state.get("observations", [])
        if not task or not observations:
            return

        intent = task[:80]
        seen: set[str] = set()
        for obs in observations:
            if ":" not in obs:
                continue
            tool_name, result = obs.split(":", 1)
            tool_name = tool_name.strip()
            result = result.strip()
            if not tool_name or tool_name in ("FINISH",) or tool_name in seen:
                continue
            seen.add(tool_name)
            failed = result.lower().startswith(("error", "skipped"))
            verdict = "FAILED" if failed else "succeeded"
            text = (
                f"[OUTCOME] tool '{tool_name}' {verdict} for intent: {intent} "
                f"→ {result[:160]}"
            )
            try:
                await self.memory_service.store(
                    session_id=context.session_id,
                    role="system",
                    text=text,
                    subtype="outcome",
                    importance=0.55 if failed else 0.45,
                )
            except Exception:
                logger.debug("Failed to store outcome record", exc_info=True)

    async def _retrieve_outcomes(self, task: str, top_k: int = 3) -> str:
        """Return a formatted block of relevant past tool outcomes (or '')."""
        if self.memory_service is None or not getattr(self.memory_service, "is_enabled", False):
            return ""
        from src.core.config import get_settings

        if not getattr(get_settings(), "ENABLE_REFLECTIVE_LEARNING", True):
            return ""
        try:
            results = await self.memory_service.retrieve(task, top_k=top_k * 3)
        except Exception:
            return ""
        lines = [
            r.text for r in results
            if getattr(r, "subtype", "") == "outcome"
        ][:top_k]
        if not lines:
            return ""
        return "\n[PAST OUTCOMES — prefer approaches that succeeded, avoid ones that FAILED]\n" + \
            "\n".join(f"- {ln}" for ln in lines) + "\n"

    @staticmethod
    def _needs_approval(tool: Any) -> bool:
        """Risky tools (confirmation-gated or high/critical risk) require HITL."""
        if getattr(tool, "requires_confirmation", False):
            return True
        capability = getattr(tool, "capability", None)
        risk = getattr(capability, "risk_level", None) or getattr(tool, "risk_level", "low")
        return risk in ("high", "critical")

    @staticmethod
    def _approval_granted(decision: Any) -> bool:
        """Interpret an HITL resume value as approve/deny.

        Accepts a bool, a dict with an ``approved``/``approve`` key, or a
        yes/no-ish string. Anything unrecognized is treated as denial (fail
        safe — never run a risky tool without explicit approval).
        """
        if isinstance(decision, bool):
            return decision
        if isinstance(decision, dict):
            return bool(decision.get("approved", decision.get("approve", False)))
        if isinstance(decision, str):
            return decision.strip().lower() in ("yes", "y", "approve", "approved", "true", "ok")
        return False

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
