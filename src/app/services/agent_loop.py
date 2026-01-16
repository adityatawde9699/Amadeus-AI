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
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from src.infra.tools.base import Tool, ToolExecutor
from src.app.services.tool_registry import ToolRegistry


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
# REACT AGENT
# =============================================================================

class ReActAgent:
    """
    ReAct (Reason + Act) Agent for multi-step task execution.
    
    The agent follows this loop:
    1. Think about what to do next
    2. Choose and execute an action (tool)
    3. Observe the result
    4. Decide if done or continue
    
    This allows handling complex requests like:
    - "Get the weather and my tasks for today"
    - "Check system status and clear low priority reminders"
    """
    
    # Special action to indicate task completion
    FINISH_ACTION = "FINISH"
    
    def __init__(
        self,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
        llm_generate: Callable[[str], str] | None = None,
        max_iterations: int = 5,
        verbose: bool = False,
    ):
        """
        Initialize the ReAct agent.
        
        Args:
            tool_registry: Registry of available tools
            tool_executor: Executor for running tools
            llm_generate: Function to call LLM (None = use keyword matching)
            max_iterations: Maximum steps before forcing completion
            verbose: Enable debug logging
        """
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor
        self.llm_generate = llm_generate
        self.max_iterations = max_iterations
        self.verbose = verbose
    
    async def run(self, task: str, context: str = "") -> AgentResult:
        """
        Execute a task using the ReAct loop.
        
        Args:
            task: The user's request
            context: Additional context (conversation history, etc.)
            
        Returns:
            AgentResult with final answer and execution trace
        """
        steps: list[AgentStep] = []
        tools_used: list[str] = []
        observations: list[str] = []
        
        for i in range(self.max_iterations):
            step_num = i + 1
            
            # Build the scratchpad of previous steps
            scratchpad = "\n\n".join(s.to_prompt() for s in steps)
            
            # Step 1: THINK - Decide what to do
            thought, action, action_input = await self._think(
                task=task,
                context=context,
                scratchpad=scratchpad,
                observations=observations,
            )
            
            step = AgentStep(
                step_number=step_num,
                thought=thought,
                action=action,
                action_input=action_input,
            )
            
            if self.verbose:
                logger.info(f"Step {step_num}: {thought} -> {action}")
            
            # Step 2: Check if FINISH
            if action == self.FINISH_ACTION:
                # The "action_input" contains the final answer
                final_answer = action_input.get("answer", thought)
                step.observation = "Task complete"
                steps.append(step)
                
                return AgentResult(
                    success=True,
                    final_answer=final_answer,
                    steps=steps,
                    tools_used=tools_used,
                    total_iterations=step_num,
                )
            
            # Step 3: ACT - Execute the tool
            tool = self.tool_registry.get(action)
            if not tool:
                step.observation = f"Error: Tool '{action}' not found"
                steps.append(step)
                continue
            
            try:
                result = await self.tool_executor.execute(tool, action_input)
                observation = str(result.result) if result.success else f"Error: {result.error_message}"
                tools_used.append(action)
            except Exception as e:
                observation = f"Error executing {action}: {e}"
                logger.error(f"Tool execution error: {e}")
            
            # Step 4: OBSERVE - Record the result
            step.observation = observation
            observations.append(f"{action}: {observation}")
            steps.append(step)
        
        # Max iterations reached - synthesize what we have
        final_answer = await self._synthesize_answer(task, observations)
        
        return AgentResult(
            success=True,
            final_answer=final_answer,
            steps=steps,
            tools_used=tools_used,
            total_iterations=self.max_iterations,
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
        """
        # Get available tools
        tool_descriptions = []
        for name in self.tool_registry.list_names():
            tool = self.tool_registry.get(name)
            if tool:
                tool_descriptions.append(f"- {name}: {tool.description}")
        
        prompt = f"""You are an AI assistant executing a multi-step task.

Task: {task}
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
            response = self.llm_generate(prompt)
            return self._parse_llm_response(response)
        except Exception as e:
            logger.error(f"LLM reasoning error: {e}")
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
            try:
                action_input = json.loads(input_match.group(1))
            except json.JSONDecodeError:
                pass
        
        return (thought, action, action_input)
    
    async def _synthesize_answer(self, task: str, observations: list[str]) -> str:
        """Combine observations into a final answer."""
        if not observations:
            return "I couldn't find relevant information for your request."
        
        # Simple concatenation for keyword mode
        parts = []
        for obs in observations:
            # Clean up the observation
            if ":" in obs:
                tool, result = obs.split(":", 1)
                parts.append(result.strip())
            else:
                parts.append(obs)
        
        return " ".join(parts)


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_react_agent(
    tool_registry: ToolRegistry,
    tool_executor: ToolExecutor,
    llm_generate: Callable[[str], str] | None = None,
    max_iterations: int = 5,
) -> ReActAgent:
    """Create a ReAct agent with the given configuration."""
    return ReActAgent(
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        llm_generate=llm_generate,
        max_iterations=max_iterations,
    )
