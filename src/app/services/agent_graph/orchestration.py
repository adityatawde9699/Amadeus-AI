"""Orchestrator, supervisor, step collection and synthesis nodes + routers.

Mixin of ``AmadeusGraph`` (see ``agent_loop.py``); split out of the former
single 1,300-line module without changing any method body.
"""

from __future__ import annotations

import logging
from typing import Literal

from src.app.services.agent_graph.actions import ActionHelpers
from src.app.services.agent_graph.base import GraphBase

# Runtime import (not TYPE_CHECKING): LangGraph resolves node type hints when
# the graph is built, so AmadeusState must be importable here.
from src.app.services.agent_graph.state import AmadeusState  # noqa: TC001
from src.core.domain.agent_profiles import (
    AGENT_PROFILES,
)
from src.core.prompt_safety import (
    UNTRUSTED_DATA_NOTICE,
    wrap_untrusted,
    wrap_user_task,
)


logger = logging.getLogger(__name__)


class OrchestrationNodes(ActionHelpers, GraphBase):
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

User request:
{wrap_user_task(task)}

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
        fenced = "\n".join(wrap_untrusted(r, source="expert_result") for r in step_results)

        if not self.llm_generate:
            # No LLM: return the concatenated expert outputs directly.
            return "\n".join(r.split("] ", 1)[-1] for r in step_results)

        prompt = f"""You are Amadeus AI. The user's request was handled by several \
specialized experts in sequence. Combine their results into a single, coherent \
response. Do not mention the experts or the internal steps.

{UNTRUSTED_DATA_NOTICE}

User request:
{wrap_user_task(root_task)}

Expert results:
{fenced}

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
