"""An expert whose tools are not registered must say so, not invent an answer."""

from __future__ import annotations

import pytest

from src.app.services.agent_loop import AmadeusGraph
from src.app.services.tool_registry import ToolRegistry
from src.core.domain.context import RequestContext
from src.core.domain.models import PermissionProfile
from src.infra.tools.base import Tool, ToolCategory


class _Executor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(self, tool, args, **_):
        self.calls.append(tool.name)
        return type("R", (), {"success": True, "result": "ok", "error_message": None})()


@pytest.mark.asyncio
async def test_expert_with_no_registered_tools_does_not_call_the_llm():
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="get_weather",
            function=lambda **_: "sunny",
            category=ToolCategory.WEATHER,
            description="Weather.",
        )
    )  # nothing in the COMMUNICATION category: email is disabled
    llm_prompts: list[str] = []

    async def llm(prompt: str, **_: object) -> str:
        llm_prompts.append(prompt)
        return '{"tool": "FINISH", "args": {"answer": "No unread emails found."}}'

    executor = _Executor()
    graph = AmadeusGraph(
        tool_registry=registry, tool_executor=executor, llm_generate=llm, max_iterations=2
    )
    ctx = RequestContext(
        request_id="t", session_id="t-email", user_id="t", permissions=PermissionProfile.SYSTEM_FULL
    )
    result = await graph.ainvoke(
        task="check my inbox for unread email",
        context=ctx,
        routing_intent="expert",
        routing_target="email_expert",
        allow_orchestration=False,
    )

    assert "no tools enabled" in result.final_answer
    assert "No unread emails" not in result.final_answer
    assert executor.calls == [] and llm_prompts == []
