"""Expert plan → tool → reflect nodes (schema-constrained action selection).

Mixin of ``AmadeusGraph`` (see ``agent_loop.py``); split out of the former
single 1,300-line module without changing any method body.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import TYPE_CHECKING, Any

from langgraph.types import interrupt

from src.app.services.action_schema import build_action_schema
from src.app.services.agent_graph.actions import ActionHelpers
from src.app.services.agent_graph.base import GraphBase
from src.app.services.agent_graph.outcomes import OutcomeMemory

# Runtime import (not TYPE_CHECKING): LangGraph resolves node type hints when
# the graph is built, so AmadeusState must be importable here.
from src.app.services.agent_graph.state import AmadeusState  # noqa: TC001
from src.core.domain.models import PermissionProfile
from src.core.prompt_safety import (
    UNTRUSTED_DATA_NOTICE,
    render_observations,
    wrap_untrusted,
    wrap_user_task,
)


if TYPE_CHECKING:
    from collections.abc import Callable

    from src.core.domain.agent_profiles import AgentProfile


logger = logging.getLogger(__name__)


class ExpertNodes(ActionHelpers, OutcomeMemory, GraphBase):
    @staticmethod
    def _accepts_kwarg(fn: Callable[..., Any] | None, name: str) -> bool:
        if fn is None:
            return False
        try:
            params = inspect.signature(fn).parameters.values()
        except (TypeError, ValueError):
            return False
        return any(p.name == name or p.kind is inspect.Parameter.VAR_KEYWORD for p in params)

    def _expert_tools(self, profile: AgentProfile) -> list[Any]:
        if profile.categories:
            return self.tool_registry.get_tools_by_categories(list(profile.categories))
        return self.tool_registry.list_all()

    async def _generate_action(self, prompt: str, profile: AgentProfile, lead: str) -> str:
        """Ask the LLM for one action, schema-constrained when supported.

        The schema restricts ``tool`` to the expert's tools (+ FINISH) and
        ``args`` to their real parameter names; llama.cpp turns it into a
        grammar (see ``action_schema``). Callers without a ``json_schema``
        kwarg fall back to plain structured mode.
        """
        assert self.llm_generate is not None
        if not self._llm_accepts_schema:
            return await self.llm_generate(prompt, structured=True)
        schema = build_action_schema(self._expert_tools(profile), lead=lead)
        return await self.llm_generate(prompt, structured=True, json_schema=schema)

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
                            memory_block = (
                                "\n[RETRIEVED MEMORIES]\n"
                                f"{wrap_untrusted(formatted, source='memory')}\n"
                            )
                except Exception:
                    pass

            # Phase 4: inject relevant past tool outcomes (reflective learning).
            outcome_block = await self._retrieve_outcomes(task)

            json_template = """{\n  "plan": "step-by-step plan",\n  "tool": "first_tool_name or FINISH",\n  "args": {"<exact parameter name from the tool list>": "value"},\n  "intent": "your reasoning"\n}"""
            prompt = f"""{profile.system_prompt_preamble}

{UNTRUSTED_DATA_NOTICE}

Task:
{wrap_user_task(task)}
{memory_block}{outcome_block}

Available Tools (you may ONLY use these):
{tool_menu}
- FINISH: Use when task is complete. Input: {{"answer": "your final response"}}

Create a plan and decide the FIRST action. The keys in "args" MUST be the exact
parameter names shown in parentheses after the tool name. Respond with JSON only:
{json_template}"""
            try:
                response = await self._generate_action(prompt, profile, lead="plan")
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
        # Taint gate: once external content is in context, a state-changing tool
        # may be the result of an injected instruction — require a human.
        taint_gate = (
            bool(state.get("untrusted_context"))
            and self._is_mutating(tool)
            and not getattr(tool, "requires_confirmation", False)
        )
        if taint_gate:
            logger.info("Taint gate: '%s' after untrusted content — approval required", tool_name)

        approved_in_graph = False
        if state.get("allow_hitl") and (self._needs_approval(tool) or taint_gate):
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
            approved_in_graph = True

        try:
            from src.app.services.tool_dispatcher import ToolDispatcher
            timeout = ToolDispatcher.TOOL_TIMEOUTS.get(tool_name, ToolDispatcher.DEFAULT_TIMEOUT)
            result = await asyncio.wait_for(
                self.tool_executor.execute(
                    tool, tool_args,
                    permission_profile=permission_profile,
                    session_id=state.get("session_id"),
                    # Without in-graph HITL, enforce the taint gate through the
                    # executor's confirmation channel (fails closed if none).
                    force_confirmation=taint_gate and not approved_in_graph,
                ),
                timeout=timeout,
            )
            observation = (
                str(result.result) if result.success else f"Error: {result.error_message}"
            )
            tool_used = [tool_name] if result.success else []
            update: dict = {
                "observations": [f"{tool_name}: {observation}"],
                "tools_used": tool_used,
                "should_continue": True,
            }
            if result.success and self._returns_external_content(tool):
                update["untrusted_context"] = True
            return update
        except TimeoutError:
            return {
                "observations": [f"{tool_name}: Error — timed out after {timeout}s"],
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
            obs_text = render_observations(observations[-5:])

            # Expert-constrained tool menu
            if profile.categories:
                tool_menu = self.tool_registry.get_tools_menu_for_categories(
                    list(profile.categories)
                )
            else:
                tool_menu = self.tool_registry.get_tools_menu()

            json_template = """{\n  "intent": "your reasoning",\n  "tool": "next_tool_name or FINISH",\n  "args": {"<exact parameter name from the tool list>": "value"}\n}"""
            prompt = f"""{profile.system_prompt_preamble}

{UNTRUSTED_DATA_NOTICE}

Plan: {plan}
Task:
{wrap_user_task(task)}

Available Tools (you may ONLY use these):
{tool_menu}
- FINISH: Use when task is complete. Input: {{"answer": "your final response"}}

Previous observations:
{obs_text}

Iteration: {iteration}/{max_iterations}

Decide the next action. If the task is complete, use FINISH.
The keys in "args" MUST be the exact parameter names shown in parentheses after the tool name.
Respond with JSON only:
{json_template}"""
            try:
                response = await self._generate_action(prompt, profile, lead="intent")
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

        # Arithmetic: "how much is 2345/2x4" → calculate("2345/2x4").
        # Lets plain math work even when no LLM is available.
        if "calculate" not in done_tools and "calculate" in allowed_tools:
            expr = self._extract_math_expression(task)
            if expr:
                return "calculate", {"expression": expr}

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
