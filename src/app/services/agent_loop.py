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

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field


class QueueFullError(Exception):
    """Raised when the AgentOrchestrator queue is full and cannot accept new requests."""

from src.app.services.tool_registry import ToolRegistry
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

    def to_prompt(self) -> str:
        """Format step for inclusion in prompt."""
        lines = [f"Step {self.step_number}:"]
        lines.append(f"Thought: {self.thought}")
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


# =============================================================================
# REACT AGENT STATE MACHINE
# =============================================================================

import asyncio
import contextlib
from enum import Enum


class AgentState(Enum):
    """States for the Agent State Machine."""
    START = "START"
    THINK = "THINK"
    ACT = "ACT"
    OBSERVE = "OBSERVE"
    SYNTHESIZE = "SYNTHESIZE"
    END = "END"


class ReActAgent:
    """
    ReAct (Reason + Act) Agent implemented as an async state machine.

    The agent follows this loop:
    START -> THINK -> ACT -> OBSERVE -> ... -> SYNTHESIZE -> END

    This avoids blocking while loops and supports structured asynchronous execution
    via `asyncio.Queue` for handling inter-step communications.
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

    async def run(
        self,
        task: str,
        context: str = "",
        permission_profile: PermissionProfile = PermissionProfile.SYSTEM_FULL,
    ) -> AgentResult:
        """
        Execute a task using the async State Machine built on asyncio.Queue.

        Args:
            task: The user's request
            context: Additional context
            permission_profile: Security clearance for this specific request

        Returns:
            AgentResult with final answer and execution trace
        """
        self.task = task
        self.context = context
        self.permission_profile = permission_profile
        self.steps: list[AgentStep] = []
        self.tools_used: list[str] = []
        self.observations: list[str] = []
        self.iteration = 0

        self.queue: asyncio.Queue[AgentState] = asyncio.Queue()
        await self.queue.put(AgentState.START)

        final_answer = ""
        success = False

        # Async State Machine Processing Loop
        while not self.queue.empty():
            state = await self.queue.get()

            if self.verbose:
                logger.debug(f"Agent State: {state.value} | Iteration: {self.iteration}")

            if state == AgentState.START:
                await self.queue.put(AgentState.THINK)

            elif state == AgentState.THINK:
                if self.iteration >= self.max_iterations:
                    if self.verbose:
                        logger.debug("Max iterations reached. Defaulting to exact synthesize.")
                    await self.queue.put(AgentState.SYNTHESIZE)
                    continue

                self.iteration += 1
                scratchpad = "\n\n".join(s.to_prompt() for s in self.steps)

                thought, action, action_input = await self._think(
                    task=self.task,
                    context=self.context,
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

                if action == self.FINISH_ACTION:
                    final_answer = action_input.get("answer", thought)
                    step.observation = "Task complete"
                    self.steps.append(step)
                    success = True
                    await self.queue.put(AgentState.END)
                else:
                    await self.queue.put(AgentState.ACT)

            elif state == AgentState.ACT:
                action = self.current_step.action or ""
                action_input = self.current_step.action_input

                tool = self.tool_registry.get(action)
                if not tool:
                    self.current_step.observation = f"Error: Tool '{action}' not found"
                    self.steps.append(self.current_step)
                    await self.queue.put(AgentState.THINK)
                    continue

                try:
                    result = await self.tool_executor.execute(
                        tool,
                        action_input,
                        permission_profile=self.permission_profile,
                    )
                    self.current_observation = str(result.result) if result.success else f"Error: {result.error_message}"
                    self.tools_used.append(action)
                except Exception as e:
                    self.current_observation = f"Error executing {action}: {e}"
                    logger.exception(f"Tool execution error: {e}")

                await self.queue.put(AgentState.OBSERVE)

            elif state == AgentState.OBSERVE:
                self.current_step.observation = self.current_observation
                self.observations.append(f"{self.current_step.action}: {self.current_observation}")
                self.steps.append(self.current_step)

                await self.queue.put(AgentState.THINK)

            elif state == AgentState.SYNTHESIZE:
                final_answer = await self._synthesize_answer(self.task, self.observations)
                success = True
                await self.queue.put(AgentState.END)

            elif state == AgentState.END:
                # 3. Learning Step - Extract entities/relationships from this interaction
                await self._learn_from_interaction(self.task, final_answer)
                break


        return AgentResult(
            success=success,
            final_answer=final_answer,
            steps=self.steps,
            tools_used=self.tools_used,
            total_iterations=self.iteration,
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

        # Define intent patterns
        intents = [
            (["time", "what time", "current time"], "get_datetime_info", {"query": "time"}),
            (["date", "what day", "today"], "get_datetime_info", {"query": "date"}),
            (["joke", "make me laugh", "funny"], "tell_joke", {}),
            (["weather"], "get_weather", {"location": "India"}),
            (["system", "cpu", "memory", "status"], "system_status", {}),
            (["task", "tasks", "todo"], "list_tasks", {}),
            (["note", "notes"], "list_notes", {}),
            (["reminder", "reminders"], "list_reminders", {}),
            (["battery"], "get_battery_info", {}),
            (["news", "headlines"], "get_news", {}),
        ]

        # Find next action
        for keywords, tool_name, tool_input in intents:
            if tool_name in done_tools:
                continue
            if any(kw in task_lower for kw in keywords):
                thought = f"User wants {tool_name.replace('_', ' ')}"
                return (thought, tool_name, tool_input)

        # All done - synthesize answer
        if observations:
            combined = "; ".join(observations)
            return (
                "All requested information gathered",
                self.FINISH_ACTION,
                {"answer": combined}
            )

        # Nothing matched
        return (
            "I don't have a specific tool for this request",
            self.FINISH_ACTION,
            {"answer": "I'm not sure how to help with that. Try asking about time, weather, tasks, or system status."}
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
        Injects top-k semantic memories AND Knowledge Graph facts into the prompt.
        """
        # Get available tools
        tool_descriptions = []
        for name in self.tool_registry.list_names():
            tool = self.tool_registry.get(name)
            if tool:
                tool_descriptions.append(f"- {name}: {tool.description}")

        # 1. Retrieve semantic memories (Qdrant)
        memory_block = ""
        if self.memory_service is not None:
            try:
                memories = await self.memory_service.retrieve(task, top_k=3)  # type: ignore[attr-defined]
                if memories:
                    formatted = self.memory_service.format_for_prompt(memories)  # type: ignore[attr-defined]
                    if formatted:
                        memory_block = f"Past Context (Semantic):\n{formatted}\n\n"
            except Exception as mem_err:
                logger.debug("Memory retrieval skipped: %s", mem_err)

        # 2. Retrieve Graph Facts (Episodic)
        graph_block = ""
        # Check if graph_repo is available (we'll need to inject this or get from service)
        graph_repo = getattr(self, "graph_repo", None)
        if graph_repo:
            try:
                # Extract potential entity names from task using LLM
                potential_entities = []
                if self.llm_generate:
                    try:
                        extract_prompt = f"Extract all named entities (people, places, projects, things) from the following text. Return ONLY a comma-separated list of names (no explanation).\\nText: {task}"
                        extracted = await self.llm_generate(extract_prompt)
                        potential_entities = [e.strip(" '\\\"") for e in extracted.split(",") if e.strip()]
                    except Exception as e:
                        logger.debug(f"Entity extraction failed, falling back to heuristic: {e}")

                if not potential_entities:
                    words = task.split()
                    potential_entities = [w.strip("?,.!") for w in words if w and w[0].isupper()]

                facts = []
                for entity in potential_entities:
                    rel_triples = await graph_repo.find_relationships_by_entity(entity)
                    for t in rel_triples:
                        facts.append(f"{t['subject']} {t['predicate']} {t['object']}")

                if facts:
                    graph_block = "Known Facts (Relationships):\\n- " + "\\n- ".join(list(set(facts))[:10]) + "\\n\\n"
            except Exception as graph_err:
                logger.debug("Graph fact retrieval skipped: %s", graph_err)

        prompt = f"""You are an AI assistant executing a multi-step task.

{memory_block}{graph_block}Task: {task}
{f"Context: {context}" if context else ""}

Available Tools:
{chr(10).join(tool_descriptions[:15])}
- FINISH: Use when task is complete. Input: {{"answer": "your final response"}}

Previous Steps:
{scratchpad if scratchpad else "(none yet)"}

Based on the task and what you've already done, decide the next action.
Respond in this exact format:
Thought: [your reasoning]
Action: [tool_name or FINISH]
Action Input: {{"param": "value"}}

Your response:"""

        try:
            assert self.llm_generate is not None
            response = await self.llm_generate(prompt)
            return self._parse_llm_response(response)
        except Exception as e:
            logger.exception(f"LLM reasoning error: {e}")
            # Fallback to keywords
            return await self._think_with_keywords(task, observations)


    def _parse_llm_response(self, response: str) -> tuple[str, str, dict]:
        """Parse LLM response into thought, action, input."""
        import json
        import re

        thought = ""
        action = self.FINISH_ACTION
        action_input = {}

        # Extract thought
        thought_match = re.search(r"Thought:\s*(.+?)(?=Action:|$)", response, re.DOTALL)
        if thought_match:
            thought = thought_match.group(1).strip()

        # Extract action
        action_match = re.search(r"Action:\s*(\w+)", response)
        if action_match:
            action = action_match.group(1)

        # Extract action input
        input_match = re.search(r"Action Input:\s*(\{.+?\})", response, re.DOTALL)
        if input_match:
            with contextlib.suppress(json.JSONDecodeError):
                action_input = json.loads(input_match.group(1))

        return (thought, action, action_input)

    async def _learn_from_interaction(self, task: str, answer: str) -> None:
        """
        Extract new entities and relationships from the user task and assistant response.
        Updates the Knowledge Graph repository.
        """
        graph_repo = getattr(self, "graph_repo", None)
        if not graph_repo or not self.llm_generate:
            return

        learn_prompt = f"""Extract relationships (Subject, Predicate, Object) from this interaction.
User: {task}
Assistant: {answer}

Respond ONLY with a JSON list of triples, or an empty list [].
Example: [{{"subject": "Sarah", "predicate": "is_boss_of", "object": "User", "type": "person"}}]

Relationships:"""

        try:
            response = await self.llm_generate(learn_prompt)
            import json
            import re

            # Clean JSON from markdown if present
            match = re.search(r"\[.*\]", response, re.DOTALL)
            if match:
                triples = json.loads(match.group(0))
                for t in triples:
                    sub = t.get("subject")
                    pred = t.get("predicate")
                    obj = t.get("object")
                    e_type = t.get("type", "unknown")

                    if sub and pred and obj:
                        sub_id = await graph_repo.upsert_entity(sub, entity_type=e_type)
                        obj_id = await graph_repo.upsert_entity(obj)
                        await graph_repo.add_relationship(sub_id, pred, obj_id)
                        logger.info(f"Learned relationship: {sub} -> {pred} -> {obj}")
        except Exception as e:
            logger.debug("Learning step failed: %s", e)

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


from collections.abc import Callable


# =============================================================================
# SPECIALIZED SUB-AGENTS
# =============================================================================

class SystemAgent(ReActAgent):
    """
    Specialized agent for OS-level interactions and system controls.
    """
    def __init__(self, tool_registry: ToolRegistry, tool_executor: ToolExecutor, llm_generate: Callable[[str], Awaitable[str]] | None = None):
        super().__init__(
            tool_registry=tool_registry,
            tool_executor=tool_executor,
            llm_generate=llm_generate,
            max_iterations=3,
        )

class ResearchAgent(ReActAgent):
    """
    Specialized agent for gathering information, checking the weather,
    getting news, and analyzing documents.
    """
    def __init__(self, tool_registry: ToolRegistry, tool_executor: ToolExecutor, llm_generate: Callable[[str], Awaitable[str]] | None = None):
        super().__init__(
            tool_registry=tool_registry,
            tool_executor=tool_executor,
            llm_generate=llm_generate,
            max_iterations=5,
        )


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
    ):
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor
        self.llm_generate = llm_generate
        self.memory_service = memory_service
        self.max_queue_size = max_queue_size

        self.queue: asyncio.Queue[tuple[str, str, PermissionProfile, asyncio.Future]] = asyncio.Queue(maxsize=self.max_queue_size)

        # Initialize Sub-Agents (all share the same memory_service)
        self.agents = {
            "system": SystemAgent(tool_registry, tool_executor, llm_generate),
            "research": ResearchAgent(tool_registry, tool_executor, llm_generate),
            "general": ReActAgent(tool_registry, tool_executor, llm_generate, max_iterations=4, memory_service=memory_service),
        }

        # Try loading SVM model for intent routing
        self.vectorizer = None
        self.classifier = None
        self._load_classifier()

        # Start the background worker loop
        self._worker_task = asyncio.create_task(self._process_queue())

    def _load_classifier(self) -> None:
        """Load TF-IDF vectorizer and SVM classifier tailored for intent routing."""
        import os

        import joblib

        try:
            vectorizer_path = "Model/router_vectorizer.joblib"
            classifier_path = "Model/router_classifier.joblib"

            if os.path.exists(vectorizer_path) and os.path.exists(classifier_path):
                self.vectorizer = joblib.load(vectorizer_path)
                self.classifier = joblib.load(classifier_path)
                logger.info("Agent Orchestrator SVM loaded. Dynamic routing enabled.")
            else:
                logger.warning("Agent Orchestrator SVM not found. Falling back to fuzzy keyword routing.")
        except Exception as e:
            logger.exception(f"Failed to load router classifier: {e}")

    def _predict_intent(self, task: str) -> str:
        """Predict which agent should handle this task."""
        if self.classifier and self.vectorizer:
            try:
                import numpy as np
                X = self.vectorizer.transform([task])
                scores = self.classifier.decision_function(X)[0]
                classes = self.classifier.classes_
                best_agent_idx = np.argsort(scores)[-1]
                predicted_agent = classes[best_agent_idx]

                if predicted_agent in self.agents:
                    logger.info(f"SVM routed '{task[:20]}...' to [{predicted_agent}]")
                    return predicted_agent
            except Exception as e:
                logger.exception(f"SVM routing failed: {e}")

        # Fallback Keywords
        lower_task = task.lower()
        if any(w in lower_task for w in ["open", "close", "system", "volume", "brightness", "battery"]):
            return "system"
        if any(w in lower_task for w in ["search", "weather", "news", "summarize", "find"]):
            return "research"

        return "general"

    async def _process_queue(self) -> None:
        """Background worker that pulls tasks off the queue and processes them sequentially."""
        logger.info("AgentOrchestrator worker loop started.")
        while True:
            try:
                task, context, permission_profile, future = await self.queue.get()

                intent = self._predict_intent(task)
                target_agent = self.agents.get(intent, self.agents["general"])

                logger.debug(f"Orchestrator executing task via {intent} agent...")

                try:
                    result = await target_agent.run(task, context, permission_profile=permission_profile)
                    if not future.done():
                        future.set_result(result)
                except Exception as e:
                    logger.exception(f"Agent execution failed: {e}")
                    if not future.done():
                        future.set_exception(e)
                finally:
                    self.queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Error in orchestrator loop: {e}")

    async def execute(
        self,
        task: str,
        context: str = "",
        permission_profile: PermissionProfile = PermissionProfile.SYSTEM_FULL,
    ) -> AgentResult:
        """
        Public endpoint: Submits a task to the orchestrator queue and awaits the result.
        Returns a QueueFullError if the system is drowning in requests.
        """
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        try:
            self.queue.put_nowait((task, context, permission_profile, future))
        except asyncio.QueueFull:
            logger.warning("AgentOrchestrator queue is full (maxsize=%s), rejecting request.", self.max_queue_size)
            raise QueueFullError("Agent system is currently overloaded. Please try again later.")

        # Wait for the worker to process our specific task
        result: AgentResult = await future
        return result

    async def shutdown(self) -> None:
        if hasattr(self, "_worker_task"):
            self._worker_task.cancel()
