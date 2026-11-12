from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.domain.context import RequestContext
from src.core.domain.models import PermissionProfile
from src.runtime.cognitive.core import AGENT_ENTRYPOINT, CognitiveCore
from src.runtime.cognitive.models import PlanStatus, StepStatus
from src.runtime.events import EventBus


_EVENTS = (
    "plan.created",
    "plan.step.started",
    "plan.step.completed",
    "plan.step.failed",
    "plan.completed",
    "plan.failed",
)


def _context() -> RequestContext:
    return RequestContext(
        request_id="req-cognitive",
        session_id="session-cognitive",
        user_id="user-cognitive",
        permissions=PermissionProfile.SYSTEM_FULL,
    )


def _recording_bus() -> tuple[EventBus, list[tuple[str, dict]]]:
    events: list[tuple[str, dict]] = []
    bus = EventBus()
    for name in _EVENTS:
        bus.on(name, lambda payload, name=name: events.append((name, payload)))
    return bus, events


@pytest.mark.asyncio
async def test_journal_wraps_task_handler_and_emits_events():
    bus, events = _recording_bus()

    async def handler(task: str, context: RequestContext) -> str:
        assert context.request_id == "req-cognitive"
        return f"handled: {task}"

    result = await CognitiveCore(bus, task_handler=handler).process(
        "summarize local state", _context()
    )

    assert result == "handled: summarize local state"
    assert [name for name, _ in events] == [
        "plan.created",
        "plan.step.started",
        "plan.step.completed",
        "plan.completed",
    ]
    assert all(payload["request_id"] == "req-cognitive" for _, payload in events)


@pytest.mark.asyncio
async def test_journal_reports_failure_when_no_handler_configured():
    bus, events = _recording_bus()
    result = await CognitiveCore(bus).process("do work", _context())

    assert "Task failed during execution" in result
    assert "no task handler configured" in result.lower()
    assert [name for name, _ in events][-2:] == ["plan.step.failed", "plan.failed"]


@pytest.mark.asyncio
async def test_journal_persists_one_run_in_two_sessions():
    repo = MagicMock()
    for method in ("create_plan", "add_observation", "update_step", "update_plan_status"):
        setattr(repo, method, AsyncMock())
    sessions = 0

    class _Session:
        async def __aenter__(self):
            nonlocal sessions
            sessions += 1
            return object()

        async def __aexit__(self, *exc):
            return False

    async def handler(task, context):
        return "ok"

    with (
        patch("src.infra.persistence.database.get_session", _Session),
        patch(
            "src.infra.persistence.repositories.cognitive_repository."
            "SQLAlchemyCognitiveRepository",
            return_value=repo,
        ),
    ):
        core = CognitiveCore(EventBus(), task_handler=handler, persistence_enabled=True)
        assert await core.process("t", _context()) == "ok"

    assert sessions == 2
    plan = repo.create_plan.await_args.args[0]
    assert [s.tool for s in plan.steps] == [AGENT_ENTRYPOINT]
    assert plan.steps[0].status == StepStatus.COMPLETED
    status_args = repo.update_plan_status.await_args.args
    assert status_args[1] == PlanStatus.COMPLETED
    assert status_args[2] == "ok"


@pytest.mark.asyncio
async def test_journal_persistence_failure_does_not_break_request():
    async def handler(task, context):
        return "ok"

    with patch(
        "src.infra.persistence.database.get_session", side_effect=RuntimeError("db down")
    ):
        core = CognitiveCore(EventBus(), task_handler=handler, persistence_enabled=True)
        assert await core.process("t", _context()) == "ok"
