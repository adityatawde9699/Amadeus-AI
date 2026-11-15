"""Agent guards: no finishing before acting, no success claims after failures."""

from __future__ import annotations

import pytest

from src.app.services.agent_loop import AmadeusGraph
from src.app.services.tool_registry import ToolRegistry
from src.core.domain.context import RequestContext
from src.core.domain.models import PermissionProfile
from src.infra.tools.base import Tool, ToolCategory


class _Executor:
    def __init__(self, success: bool = True) -> None:
        self.success, self.calls = success, []

    async def execute(self, tool, args, **_):
        self.calls.append((tool.name, dict(args)))
        return type(
            "R",
            (),
            {
                "success": self.success,
                "result": "Goal created",
                "error_message": "Memory service is not enabled.",
            },
        )()


def _graph(replies: list[str], executor: _Executor) -> tuple[AmadeusGraph, list[str]]:
    reg = ToolRegistry()
    reg.register(
        Tool(
            name="create_goal",
            function=lambda **_: "x",
            category=ToolCategory.PRODUCTIVITY,
            description="Create a goal.",
        )
    )
    prompts: list[str] = []

    async def llm(prompt: str, **_: object) -> str:
        prompts.append(prompt)
        return replies[min(len(prompts) - 1, len(replies) - 1)]

    return AmadeusGraph(
        tool_registry=reg, tool_executor=executor, llm_generate=llm, max_iterations=4
    ), prompts


async def _run(graph: AmadeusGraph):
    ctx = RequestContext(
        request_id="t",
        session_id="t-guards",
        user_id="t",
        permissions=PermissionProfile.SYSTEM_FULL,
    )
    return await graph.ainvoke(
        task="create a goal titled Learn Spanish",
        context=ctx,
        routing_intent="expert",
        routing_target="memory_expert",
        allow_orchestration=False,
    )


FINISH_EARLY = '{"plan": "p", "tool": "FINISH", "args": {"answer": "Goal already exists."}}'
CALL = '{"plan": "p", "tool": "create_goal", "args": {"title": "Learn Spanish"}}'
DONE = '{"intent": "i", "tool": "FINISH", "args": {"answer": "Goal created."}}'


@pytest.mark.asyncio
async def test_finishing_before_any_tool_call_is_retried_once():
    executor = _Executor()
    graph, prompts = _graph([FINISH_EARLY, CALL, DONE], executor)
    result = await _run(graph)
    assert executor.calls == [("create_goal", {"title": "Learn Spanish"})]
    assert "without calling a tool" in prompts[1]
    assert result.final_answer == "Goal created."


@pytest.mark.asyncio
async def test_a_second_finish_is_accepted():
    executor = _Executor()
    graph, prompts = _graph([FINISH_EARLY], executor)
    result = await _run(graph)
    assert executor.calls == [] and len(prompts) == 2
    assert result.final_answer == "Goal already exists."


@pytest.mark.asyncio
async def test_success_is_not_claimed_when_every_tool_call_failed():
    executor = _Executor(success=False)
    graph, _ = _graph([CALL, DONE], executor)
    result = await _run(graph)
    assert "couldn't complete" in result.final_answer
    assert "Memory service is not enabled" in result.final_answer
    assert "Goal created" not in result.final_answer


def test_step_failure_helper():
    f = AmadeusGraph._step_failure
    assert f([]) is None
    assert f(["a: Error: boom"]) == "boom"
    assert f(["a: Error — timed out", "b: Error: nope"]) == "nope"
    assert f(["a: Error: boom", "b: 42"]) is None  # one call worked
    assert f(["FINISH: done"]) is None
