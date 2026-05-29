from __future__ import annotations

import pytest

from src.core.domain.context import RequestContext
from src.core.domain.models import PermissionProfile
from src.runtime.cognitive.core import CognitiveCore
from src.runtime.events import EventBus


def _context() -> RequestContext:
    return RequestContext(
        request_id="req-cognitive",
        session_id="session-cognitive",
        user_id="user-cognitive",
        permissions=PermissionProfile.SYSTEM_FULL,
    )


@pytest.mark.asyncio
async def test_cognitive_core_wraps_task_handler_and_emits_events():
    events: list[tuple[str, dict]] = []
    bus = EventBus()

    for event_name in ("plan.created", "plan.step.completed", "memory.committed"):
        bus.on(event_name, lambda payload, name=event_name: events.append((name, payload)))

    async def handler(task: str, context: RequestContext) -> str:
        assert context.request_id == "req-cognitive"
        return f"handled: {task}"

    core = CognitiveCore(bus, task_handler=handler)

    result = await core.process("summarize local state", _context())

    assert result == "handled: summarize local state"
    assert [name for name, _payload in events] == [
        "plan.created",
        "plan.step.completed",
        "memory.committed",
    ]
    assert all(payload["request_id"] == "req-cognitive" for _name, payload in events)


@pytest.mark.asyncio
async def test_cognitive_core_blocks_when_no_handler_configured():
    core = CognitiveCore(EventBus())

    result = await core.process("do work", _context())

    assert "Task failed during execution" in result
    assert "no task handler configured" in result.lower()
