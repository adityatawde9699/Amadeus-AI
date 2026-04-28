"""
Unit tests for ReActAgent cycle guard behavior.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.services.agent_loop import ReActAgent


@pytest.mark.asyncio
async def test_cycle_guard_breaks_repeated_tool_input_loop() -> None:
    """
    ReActAgent should stop when the LLM repeats the same tool+input pair.
    """
    registry = MagicMock()
    registry.list_names.return_value = ["get_datetime_info"]
    registry.get.return_value = SimpleNamespace(
        name="get_datetime_info", description="Get time and date"
    )

    executor = MagicMock()
    executor.execute = AsyncMock(return_value=SimpleNamespace(success=True, result="10:00 AM"))

    llm_generate = AsyncMock(
        return_value='Thought: check time\nAction: get_datetime_info\nAction Input: {"query":"time"}'
    )

    agent = ReActAgent(
        tool_registry=registry,
        tool_executor=executor,
        llm_generate=llm_generate,
        max_iterations=5,
    )

    result = await agent.run("Tell me the current time")

    assert result.success is True
    # The repeated action should be executed only once before guard exits.
    assert result.tools_used == ["get_datetime_info"]
    assert result.total_iterations == 2
    assert executor.execute.await_count == 1
    assert llm_generate.await_count == 2
