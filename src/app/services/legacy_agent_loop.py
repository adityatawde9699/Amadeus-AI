"""
ReAct Agent Loop for Amadeus AI.

Implements the Reason-Act-Observe pattern for multi-step reasoning.
This allows the AI to chain multiple tool calls to complete complex tasks.

Example:
    User: "Check the time and tell me a joke"
    Agent:
        1. Think: Need to get time first
        2. Act: Call get_datetime_info
        3. Observe: Got "06:10 PM"
        4. Think: Now need to tell a joke
        5. Act: Call tell_joke
        6. Observe: Got joke
        7. Return: Combined response
"""

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path


class QueueFullError(Exception):
    """Raised when the AgentOrchestrator queue is full and cannot accept new requests."""


from src.app.services.tool_registry import ToolRegistry
from src.core.domain.action import AgentAction
from src.core.domain.context import RequestContext
from src.core.domain.models import PermissionProfile
from src.infra.tools.base import ToolExecutor


logger = logging.getLogger(__name__)


# =============================================================================
# DATA STRUCTURES
# =============================================================================


@dataclass
class AgentStep:
    """Single step in the agent's reasoning process."""

    step_number: int
    thought: str
    action: str | None = None
    action_input: dict = field(default_factory=dict)
    observation: str | None = None
    plan_update: str | None = None

    def to_prompt(self) -> str:
        """Format step for inclusion in prompt."""
        lines = [f"Step {self.step_number}:"]
        lines.append(f"Thought: {self.thought}")
        if self.plan_update:
            lines.append(f"Plan Update: {self.plan_update}")
        if self.action:
            lines.append(f"Action: {self.action}")
            if self.action_input:
                lines.append(f"Action Input: {self.action_input}")
        if self.observation:
            lines.append(f"Observation: {self.observation}")
        return "\n".join(lines)


@dataclass
class AgentResult:
    """Final result from agent execution."""

    success: bool
    final_answer: str
    steps: list[AgentStep] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    total_iterations: int = 0
    error: str | None = None
    plan: str | None = None


# =============================================================================
# REACT AGENT STATE MACHINE
# =============================================================================

import asyncio
import contextlib
from enum import Enum


class AgentState(Enum):
    """States for the Agent State Machine."""

    START = "START"
    PLAN = "PLAN"
    THINK = "THINK"
    ACT = "ACT"
    OBSERVE = "OBSERVE"
    SYNTHESIZE = "SYNTHESIZE"
    END = "END"


class ReActAgent:
    """
    Advanced ReAct Agent with Planning and Self-Correction.

    The agent follows this loop:
    START -> PLAN -> THINK -> ACT -> OBSERVE -> ... -> SYNTHESIZE -> END
    """

    FINISH_ACTION = "FINISH"

    def __init__(
        self,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
        llm_generate: Callable[[str], Awaitable[str]] | None = None,
        max_iterations: int = 5,
        verbose: bool = False,
        memory_service: object | None = None,
    ):
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor
        self.llm_generate = llm_generate
        self.max_iterations = max_iterations
        self.verbose = verbose
        # Optional semantic memory service (QdrantMemoryService or compatible)
        self.memory_service = memory_service
        self.plan: str = "No plan created yet."

    async def run(
        self,
        task: str,
        context: RequestContext | None = None,
        context_summary: str = "",
    ) -> AgentResult:
        """
        Execute a task using the async State Machine.
        """
        if context is None:
            import uuid

            context = RequestContext(
                request_id=str(uuid.uuid4()),
                session_id="agent_session",
                user_id="agent_user",
                permissions=PermissionProfile.SYSTEM_FULL,
            )

        self.task = task
        self.context = context
        self.context_summary = context_summary
        self.permission_profile = context.permissions
        self.steps: list[AgentStep] = []
        self.tools_used: list[str] = []
        self.observations: list[str] = []
        self.iteration = 0
        self._seen_action_inputs: set[str] = set()
        self._action_counts: dict[str, int] = {}

        self.queue: asyncio.Queue[AgentState] = asyncio.Queue()
        await self.queue.put(AgentState.START)

        final_answer = ""
        success = False

        while not self.queue.empty():
            state = await self.queue.get()

            if state == AgentState.START:
                if self.llm_generate:
                    await self.queue.put(AgentState.PLAN)
                else:
                    await self.queue.put(AgentState.THINK)

            elif state == AgentState.PLAN:
                self.plan = await self._create_plan(task, context_summary)
                await self.queue.put(AgentState.THINK)

            elif state == AgentState.THINK:
                if self.iteration >= self.max_iterations:
                    await self.queue.put(AgentState.SYNTHESIZE)
                    continue

                self.iteration += 1
                scratchpad = self._build_scratchpad()

                thought, action, action_input = await self._think(
                    task=self.task,
                    context=self.context_summary,
                    scratchpad=scratchpad,
                    observations=self.observations,
                )

                step = AgentStep(
                    step_number=self.iteration,
                    thought=thought,
                    action=action,
                    action_input=action_input,
                )
                self.current_step = step

                if action != self.FINISH_ACTION:
                    action_signature = self._action_signature(action, action_input)
                    if action_signature in self._seen_action_inputs:
                        logger.warning("Cycle guard triggered for action '%s'", action)
                        await self.queue.put(AgentState.SYNTHESIZE)
                        continue
                    self._seen_action_inputs.add(action_signature)

                if action == self.FINISH_ACTION:
                    final_answer = action_input.get("answer", thought)
                    step.observation = "Task complete"
                    self.steps.append(step)
                    success = True
                    await self.queue.put(AgentState.END)
                else:
                    await self.queue.put(AgentState.ACT)

            elif state == AgentState.ACT:
                await self._execute_action()
                await self.queue.put(AgentState.OBSERVE)

            elif state == AgentState.OBSERVE:
                await self._process_observation()
                await self.queue.put(AgentState.THINK)

            elif state == AgentState.SYNTHESIZE:
                final_answer = await self._synthesize_answer(self.task, self.observations)
                success = bool(final_answer) and not self._is_all_errors()
                await self.queue.put(AgentState.END)

            elif state == AgentState.END:
                break

        return AgentResult(
            success=success,
            final_answer=final_answer,
            steps=self.steps,
            tools_used=self.tools_used,
            total_iterations=self.iteration,
            plan=self.plan,
        )

    def _build_scratchpad(self) -> str:
        if len(self.steps) > 5:
            return "[EARLIER STEPS SUMMARIZED]\n\n" + "\n\n".join(s.to_prompt() for s in self.steps[-5:])
        return "\n\n".join(s.to_prompt() for s in self.steps)

    async def _create_plan(self, task: str, context: str) -> str:
        """Create an initial plan for complex tasks."""
        if not self.llm_generate:
            return "No plan (keyword mode)"

        tool_menu = self.tool_registry.get_tools_menu()
        prompt = f"""You are Amadeus, an autonomous agent. Create a high-level step-by-step plan to solve this task.
Task: {task}
Context: {context}
Available Tools:
{tool_menu}

Your plan should be a simple list of steps. Do not execute anything yet.
Plan:"""
        try:
            return await self.llm_generate(prompt)
        except Exception:
            return "Failed to generate plan."

    async def _execute_action(self):
        action = self.current_step.action or ""
        action_input = self.current_step.action_input

        tool = self.tool_registry.get(action)
        if not tool:
            self.current_observation = f"Error: Tool '{action}' not found"
            return

        try:
            _timeout = 30 # Default for agent loop
            result = await asyncio.wait_for(
                self.tool_executor.execute(
                    tool,
                    action_input,
                    permission_profile=self.permission_profile,
                ),
                timeout=_timeout,
            )
            self.current_observation = (
                str(result.result) if result.success else f"Error: {result.error_message}"
            )
            self.tools_used.append(action)
        except Exception as e:
            self.current_observation = f"Error executing {action}: {e}"

    async def _process_observation(self):
        # Self-Correction Reflection
        obs_lower = self.current_observation.lower()
        if "error" in obs_lower or "failed" in obs_lower:
            self.current_observation += "\n[REFLECTION: The last action failed. I must re-evaluate my approach.]"

        self.current_step.observation = self.current_observation
        self.observations.append(f"{self.current_step.action}: {self.current_observation}")
        self.steps.append(self.current_step)

    def _is_all_errors(self) -> bool:
        return self.observations and all(
            obs.lower().startswith("error") or "error:" in obs.lower()
            for obs in self.observations
        )

    async def _think(
        self,
        task: str,
        context: str,
        scratchpad: str,
        observations: list[str],
    ) -> tuple[str, str, dict]:
        """
        Decide the next action using LLM or keyword matching.

        Returns:
            Tuple of (thought, action_name, action_input)
        """
        # If we have an LLM, use it for reasoning
        if self.llm_generate:
            return await self._think_with_llm(task, context, scratchpad, observations)

        # Fallback: keyword-based action selection
        return await self._think_with_keywords(task, observations)

    async def _think_with_keywords(
        self,
        task: str,
        observations: list[str],
    ) -> tuple[str, str, dict]:
        """
        Simple keyword-based reasoning (no LLM required).

        Detects multiple intents in the task and executes them sequentially.
        """
        task_lower = task.lower()

        # Track what we've already done
        done_tools = {obs.split(":")[0] for obs in observations}

        # 1. Check for exact tool name matches
        for tool_name in self.tool_registry.list_names():
            if tool_name in done_tools:
                continue
            if tool_name in task_lower:
                # Try to extract simple args if possible (fallback to empty)
                thought = f"User explicitly mentioned tool: {tool_name}"
                return (thought, tool_name, {})

        # 2. Check for common intent patterns
        intents = [
            (["time", "what time", "current time"], "get_datetime_info", {"query": "time"}),
            (["date", "what day", "today"], "get_datetime_info", {"query": "date"}),
            (["joke", "make me laugh", "funny"], "tell_joke", {}),
            (["weather"], "get_weather", {"location": __import__("src.core.config", fromlist=["get_settings"]).get_settings().DEFAULT_LOCATION}),
            (["system", "cpu", "memory", "status"], "system_status", {}),
            (["task", "tasks", "todo"], "list_tasks", {}),
            (["note", "notes"], "list_notes", {}),
            (["reminder", "reminders"], "list_reminders", {}),
            (["battery"], "get_battery_info", {}),
            (["news", "headlines"], "get_news", {}),
            (["email", "emails", "inbox"], "read_unread_emails", {}),
            (["calculate", "math", "solve"], "calculate", {"expression": task}),
            (["terminal", "command", "ping", "ipconfig"], "terminal_cmd", {"command": task}),
            (["plugin", "plugins"], "manage_plugins", {"action": "list"}),
            (["search code", "codebase"], "search_codebase", {"query": task}),
        ]

        # Find next action from intents
        for keywords, tool_name, tool_input in intents:
            if tool_name in done_tools:
                continue
            if any(kw in task_lower for kw in keywords):
                if tool_name in self.tool_registry:
                    thought = f"User wants {tool_name.replace('_', ' ')}"
                    return (thought, tool_name, tool_input)

        # All done - synthesize answer
        if observations:
            combined = "; ".join(observations)
            return ("All requested information gathered", self.FINISH_ACTION, {"answer": combined})

        # Nothing matched
        return (
            "I don't have a specific tool for this request",
            self.FINISH_ACTION,
            {
                "answer": "I'm not sure how to help with that. Try asking about time, weather, tasks, or system status."
            },
        )

    async def _think_with_llm(
        self,
        task: str,
        context: str,
        scratchpad: str,
        observations: list[str],
    ) -> tuple[str, str, dict]:
        """
        Use LLM for sophisticated reasoning.
        Injects the plan and previous steps into the prompt.
        """
        tool_descriptions = []
        summary = self.tool_registry.get_summary()
        for category, tool_names in summary.get("categories", {}).items():
            tool_descriptions.append(f"[{category.upper()}]")
            for name in tool_names:
                tool = self.tool_registry.get(name)
                if tool:
                    tool_descriptions.append(f"  - {name}: {tool.description}")
            tool_descriptions.append("")

        # Retrieve semantic memories
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

        prompt = f"""You are Amadeus — an advanced autonomous AI agent.

Current Plan:
{self.plan}

Task: {task}
{f"Context: {context}" if context else ""}
{memory_block}

Available Tools:
{chr(10).join(tool_descriptions)}
- FINISH: Use when task is complete. Input: {{"answer": "your final response"}}

Rules:
1. Follow the plan but adapt if tools provide new information or fail.
2. Use tools to verify facts. Do not hallucinate.
3. If an action fails, analyze the error and try a different tool or parameters.
4. Respond ONLY with a valid JSON object.

Previous Steps:
{scratchpad if scratchpad else "(none yet)"}

Decide the next action:
{{
  "intent": "your reasoning and how it relates to the plan",
  "tool": "tool_name or null if FINISH",
  "args": {{"param": "value"}},
  "requires_confirmation": false,
  "confidence": 1.0
}}"""

        try:
            if self.llm_generate is None:
                raise ValueError("llm_generate is not configured")
            response = await self.llm_generate(prompt, structured=True)
            return self._parse_llm_response(response)
        except Exception as e:
            logger.exception("LLM reasoning error: %s", e)
            return await self._think_with_keywords(task, observations)

    def _parse_llm_response(self, response: str) -> tuple[str, str, dict]:
        """Parse LLM response using AgentAction JSON schema."""

        # Clean up markdown code blocks if the LLM adds them despite instructions
        cleaned = response.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]

        cleaned = cleaned.strip()

        try:
            action_model = AgentAction.model_validate_json(cleaned)
            action = action_model.tool or self.FINISH_ACTION
            return (action_model.intent, action, action_model.args)
        except Exception as e:
            legacy = self._parse_legacy_react_response(cleaned)
            if legacy is not None:
                return legacy
            logger.error("Failed to parse LLM JSON response: %s | Raw: %s", e, cleaned)
            # Fallback for severe malformation
            return ("Failed to parse structured action.", self.FINISH_ACTION, {"answer": "I had trouble forming a structured response. Please try again."})

    def _parse_legacy_react_response(self, response: str) -> tuple[str, str, dict] | None:
        """Parse legacy Thought/Action/Action Input responses used by older tests."""
        lines = [line.strip() for line in response.splitlines() if line.strip()]
        thought = ""
        action = ""
        args: dict = {}

        for line in lines:
            if line.startswith("Thought:"):
                thought = line.split(":", 1)[1].strip()
            elif line.startswith("Action Input:"):
                raw_args = line.split(":", 1)[1].strip()
                try:
                    parsed = json.loads(raw_args)
                    if isinstance(parsed, dict):
                        args = parsed
                except json.JSONDecodeError:
                    args = {}
            elif line.startswith("Action:"):
                action = line.split(":", 1)[1].strip()

        if not action:
            return None
        return (thought or action, action, args)

    @staticmethod
    def _action_signature(action: str, action_input: dict) -> str:
        """
        Build a stable, order-independent key for an (action, args) pair.

        Used by the cycle-detection guard to identify when the agent is about
        to repeat an exact tool call it has already made in this run, which
        would produce the same observation and lead to an infinite loop.

        Args:
            action:       Tool name string.
            action_input: Arbitrary keyword arguments dict.

        Returns:
            A string of the form ``"tool_name|{...sorted json...}"`` that is
            identical for semantically equivalent calls regardless of dict
            insertion order.
        """
        import json

        normalized = json.dumps(action_input, sort_keys=True, default=str)
        return f"{action}|{normalized}"



    async def _synthesize_answer(self, task: str, observations: list[str]) -> str:
        """Combine observations into a final answer."""
        if not observations:
            return "I couldn't find relevant information for your request."

        # Simple concatenation for keyword mode
        parts = []
        for obs in observations:
            # Clean up the observation
            if ":" in obs:
                _tool, result = obs.split(":", 1)
                parts.append(result.strip())
            else:
                parts.append(obs)

        return " ".join(parts)



# =============================================================================
# AGENT ORCHESTRATOR
# =============================================================================


class AgentOrchestrator:
    """
    Central router that receives queries, predicts intent via an SVM text classifier,
    and dispatches the job to the appropriate specialized sub-agent via an asyncio.Queue.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
        llm_generate: Callable[[str], Awaitable[str]] | None = None,
        memory_service: object | None = None,
        max_queue_size: int = 50,
        worker_count: int = 5,
        auto_start: bool = True,
    ):
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor
        self.llm_generate = llm_generate
        self.memory_service = memory_service
        self.max_queue_size = max_queue_size
        self.worker_count = max(1, worker_count)

        self.queue: asyncio.Queue[tuple[str, RequestContext, str, asyncio.Future]] = (
            asyncio.Queue(maxsize=self.max_queue_size)
        )

        # Per-intent agent configuration. ReActAgent stores run state on the
        # instance, so workers create a fresh agent for each request.
        self.agent_max_iterations = {
            "system": 3,
            "research": 5,
            "general": 4,
        }
        self.agents = set(self.agent_max_iterations)

        # Try loading SVM model for intent routing
        self.vectorizer = None
        self.classifier = None
        self._load_classifier()

        # Start the background worker loop only when requested.
        # The DI container singleton should start the worker (auto_start=True),
        # but throwaway instances in webhooks/proactive_service should not
        # (auto_start=False) to avoid orphaned asyncio.Tasks.
        self._worker_task: asyncio.Task | None = None  # type: ignore[type-arg]
        self._worker_tasks: list[asyncio.Task] = []  # type: ignore[type-arg]
        if auto_start:
            for worker_id in range(self.worker_count):
                self._worker_tasks.append(
                    asyncio.create_task(self._process_queue(worker_id=worker_id))
                )
            self._worker_task = self._worker_tasks[0]

    def _load_classifier(self) -> None:
        """Load TF-IDF vectorizer and SVM classifier tailored for intent routing."""
        try:
            import joblib as _joblib
            if not hasattr(_joblib, "load"):
                logger.warning("Agent Orchestrator SVM: joblib stub detected — skipping load.")
                return
        except ImportError:
            return

        from src.core.config import get_settings

        try:
            settings = get_settings()
            vectorizer_path = str(settings.BASE_DIR / "Model" / "router_vectorizer.joblib")
            classifier_path = str(settings.BASE_DIR / "Model" / "router_classifier.joblib")

            if Path(vectorizer_path).exists() and Path(classifier_path).exists():
                self.vectorizer = _joblib.load(vectorizer_path)
                self.classifier = _joblib.load(classifier_path)
                logger.info("Agent Orchestrator SVM loaded. Dynamic routing enabled.")
            else:
                logger.warning(
                    "Agent Orchestrator SVM not found. Falling back to fuzzy keyword routing."
                )
        except Exception as e:
            logger.exception("Failed to load router classifier: %s", e)


    def _predict_intent(self, task: str) -> str:
        """Predict which agent should handle this task."""
        if self.classifier and self.vectorizer:
            try:
                import numpy as np

                x_vec = self.vectorizer.transform([task])
                scores = self.classifier.decision_function(x_vec)[0]
                classes = self.classifier.classes_
                best_agent_idx = np.argsort(scores)[-1]
                predicted_agent = classes[best_agent_idx]

                if predicted_agent in self.agents:
                    logger.info("SVM routed '%s...' to [%s]", task[:20], predicted_agent)
                    return predicted_agent
            except Exception as e:
                logger.exception("SVM routing failed: %s", e)

        # Dynamic Keyword Routing based on all registered tools
        lower_task = task.lower()

        # Check against all tool names and descriptions
        for tool_name in self.tool_registry.list_names():
            if tool_name in lower_task:
                tool = self.tool_registry.get(tool_name)
                if tool:
                    if tool.category in (ToolCategory.SYSTEM, ToolCategory.APP_CONTROL, ToolCategory.FILE_SYSTEM, ToolCategory.OS_CONTROL):
                        return "system"
                    if tool.category in (ToolCategory.WEB_RESEARCH, ToolCategory.WEATHER):
                        return "research"

        # Fallback Keywords
        if any(
            w in lower_task
            for w in [
                "open", "close", "system", "volume", "brightness",
                "battery", "mute", "screenshot", "screen", "running",
                "process", "terminate", "kill", "launch", "start",
                "apps", "programs", "windows", "plugin", "codebase",
            ]
        ):
            return "system"
        if any(
            w in lower_task
            for w in [
                "search", "weather", "news", "summarize", "find",
                "wikipedia", "web", "google", "look up", "article",
                "headlines", "temperature", "forecast",
            ]
        ):
            return "research"

        return "general"

    def _make_agent(self, intent: str) -> ReActAgent:
        """Create a fresh ReActAgent for one task execution."""
        agent_name = intent if intent in self.agent_max_iterations else "general"
        return ReActAgent(
            self.tool_registry,
            self.tool_executor,
            self.llm_generate,
            max_iterations=self.agent_max_iterations[agent_name],
            memory_service=self.memory_service if agent_name == "general" else None,
        )

    async def _process_queue(self, worker_id: int = 0) -> None:
        """Background worker that pulls tasks off the queue and processes them."""
        logger.info("AgentOrchestrator worker loop started (worker_id=%s).", worker_id)
        while True:
            try:
                task, context, context_summary, future = await self.queue.get()

                intent = self._predict_intent(task)
                target_agent = self._make_agent(intent)

                logger.debug("Orchestrator executing task via %s agent...", intent)

                try:
                    result = await target_agent.run(
                        task, context, context_summary=context_summary
                    )
                    if not future.done():
                        future.set_result(result)
                except Exception as e:
                    logger.exception("Agent execution failed: %s", e)
                    if not future.done():
                        future.set_exception(e)
                finally:
                    self.queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Error in orchestrator loop: %s", e)

    async def shutdown(self) -> None:
        """DR-02: Cancel the background worker task and wait for it to finish cleanly.

        Without this, the asyncio task becomes a zombie after FastAPI lifespan
        shutdown completes, logging 'Task exception was never retrieved' to stderr.
        """
        live_tasks = [task for task in self._worker_tasks if not task.done()]
        if (
            self._worker_task is not None
            and self._worker_task not in live_tasks
            and not self._worker_task.done()
        ):
            live_tasks.append(self._worker_task)
        if live_tasks:
            for task in live_tasks:
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.gather(*live_tasks)
            logger.info(
                "AgentOrchestrator worker tasks shut down cleanly (%d workers).",
                len(live_tasks),
            )

    async def execute(
        self,
        task: str,
        context: RequestContext,
        context_summary: str = "",
    ) -> AgentResult:
        """
        Public endpoint: Submits a task to the orchestrator queue and awaits the result.
        Returns a QueueFullError if the system is drowning in requests.

        If no background worker is running (auto_start=False), executes
        the agent inline to avoid hanging on an unserviced queue.
        """
        # If no worker task is running, execute directly (non-queued)
        if not self._worker_tasks:
            intent = self._predict_intent(task)
            target_agent = self._make_agent(intent)
            return await target_agent.run(task, context, context_summary=context_summary)

        loop = asyncio.get_running_loop()
        future = loop.create_future()

        try:
            self.queue.put_nowait((task, context, context_summary, future))
        except asyncio.QueueFull as e:
            logger.warning(
                "AgentOrchestrator queue is full (maxsize=%s), rejecting request.",
                self.max_queue_size,
            )
            raise QueueFullError("Agent system is currently overloaded. Please try again later.") from e

        # Wait for the worker to process our specific task
        result: AgentResult = await future
        return result
