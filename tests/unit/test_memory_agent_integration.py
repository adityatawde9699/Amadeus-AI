"""
Unit tests for memory injection in the ReAct agent loop.

Verifies that when a ``memory_service`` is provided, semantically relevant
memories are retrieved and prepended to the LLM prompt before inference.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest


# Stub heavy imports
for _mod in ("joblib", "google.generativeai", "openai", "groq", "sklearn"):
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)
        if _mod == "sklearn":
            for sub in ("svm", "feature_extraction", "feature_extraction.text", "externals"):
                sys.modules[f"{_mod}.{sub}"] = types.ModuleType(f"{_mod}.{sub}")


# =============================================================================
# Helpers
# =============================================================================


def _make_tool_registry():
    registry = MagicMock()
    registry.list_names.return_value = []
    registry.get.return_value = None
    return registry


def _make_tool_executor():
    return MagicMock()


def _make_memory_service(memories: list[str]):
    """Return a mock QdrantMemoryService that yields preset memories."""
    svc = MagicMock()
    svc.retrieve = AsyncMock(return_value=memories)
    svc.format_for_prompt = MagicMock(side_effect=lambda m: "\n".join(m) if m else "")
    return svc


# =============================================================================
# Tests
# =============================================================================


class TestReActAgentMemoryInjection:
    """Verify memory injection into the _think_with_llm prompt."""

    @pytest.mark.asyncio
    async def test_memory_block_injected_when_service_set(self):
        """LLM prompt should contain memory block when service returns results."""
        from src.app.services.legacy_agent_loop import ReActAgent

        captured_prompts: list[str] = []

        async def fake_llm(prompt: str, **kwargs) -> str:
            captured_prompts.append(prompt)
            return 'Thought: done\nAction: FINISH\nAction Input: {"answer": "Memory test done"}'

        memory_svc = _make_memory_service(["User prefers dark mode", "User is in Mumbai"])

        agent = ReActAgent(
            tool_registry=_make_tool_registry(),
            tool_executor=_make_tool_executor(),
            llm_generate=fake_llm,
            memory_service=memory_svc,
        )

        result = await agent.run("What are my preferences?")

        assert result.success
        # The prompt should contain the memory block
        assert len(captured_prompts) > 0
        assert len(captured_prompts) > 0
        has_memory = any("[RETRIEVED MEMORIES]" in p for p in captured_prompts)
        assert has_memory
        has_dark_mode = any("dark mode" in p for p in captured_prompts)
        assert has_dark_mode

    @pytest.mark.asyncio
    async def test_no_memory_when_service_not_set(self):
        """Without memory_service, prompt must NOT contain a memory block."""
        from src.app.services.legacy_agent_loop import ReActAgent

        captured_prompts: list[str] = []

        async def fake_llm(prompt: str, **kwargs) -> str:
            captured_prompts.append(prompt)
            return 'Thought: done\nAction: FINISH\nAction Input: {"answer": "No memory"}'

        agent = ReActAgent(
            tool_registry=_make_tool_registry(),
            tool_executor=_make_tool_executor(),
            llm_generate=fake_llm,
            memory_service=None,
        )

        result = await agent.run("Test task")

        assert result.success
        assert len(captured_prompts) > 0
        has_memory = any("[RETRIEVED MEMORIES]" in p for p in captured_prompts)
        assert not has_memory

    @pytest.mark.asyncio
    async def test_memory_service_error_does_not_crash_agent(self):
        """If memory retrieval fails, the agent should continue normally."""
        from src.app.services.legacy_agent_loop import ReActAgent

        async def fake_llm(prompt: str, **kwargs) -> str:
            return 'Thought: done\nAction: FINISH\nAction Input: {"answer": "Resilient"}'

        error_svc = MagicMock()
        error_svc.retrieve = AsyncMock(side_effect=RuntimeError("Qdrant unavailable"))
        error_svc.format_for_prompt = MagicMock(return_value="")

        agent = ReActAgent(
            tool_registry=_make_tool_registry(),
            tool_executor=_make_tool_executor(),
            llm_generate=fake_llm,
            memory_service=error_svc,
        )

        result = await agent.run("Resilience test")
        assert result.success
        assert "Resilient" in result.final_answer
