"""Orchestrator steps go to the expert that owns the tool, not the LLM's guess."""

from __future__ import annotations

import pytest

from src.app.services.agent_loop import AmadeusGraph
from src.app.services.tool_registry import ToolRegistry


def _graph(reply: str) -> AmadeusGraph:
    async def llm(prompt: str, **_: object) -> str:
        return reply

    return AmadeusGraph(tool_registry=ToolRegistry(), tool_executor=object(), llm_generate=llm)


REPLY = (
    '{"steps": [{"expert": "task_expert", "subtask": "add a task to call mom"},'
    ' {"expert": "os_expert", "subtask": "tell me the time"}]}'
)


@pytest.mark.asyncio
async def test_router_reassigns_steps():
    graph = _graph(REPLY)
    graph.subtask_router = lambda sub: "generalist" if "time" in sub else "task_expert"
    steps = await graph._decompose("add a task to call mom and then tell me the time", 3)
    assert [s["expert"] for s in steps] == ["task_expert", "generalist"]


@pytest.mark.asyncio
async def test_without_router_or_on_router_failure_the_llm_choice_stands():
    graph = _graph(REPLY)
    assert [s["expert"] for s in await graph._decompose("x", 3)] == ["task_expert", "os_expert"]

    def broken(_sub: str) -> str:
        raise RuntimeError("router down")

    graph.subtask_router = broken
    assert [s["expert"] for s in await graph._decompose("x", 3)] == ["task_expert", "os_expert"]
    graph.subtask_router = lambda _sub: "not_a_profile"
    assert [s["expert"] for s in await graph._decompose("x", 3)] == ["task_expert", "os_expert"]
