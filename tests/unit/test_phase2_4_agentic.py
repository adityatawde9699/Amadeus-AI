"""
Tests for the Phase 2-4 agentic upgrades:

  * Phase 2 — durable goal/step DAG + resume (GoalStepRepository, GoalExecutor)
  * Phase 3 — event-driven autonomy (ThresholdWatcher, FileWatcher, dispatcher)
  * Phase 4 — in-graph HITL (interrupt/resume) + reflective learning

These run against an in-memory SQLite database wired into the app's global
``get_session`` so no Postgres/Docker is required.
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import src.infra.persistence.database as db
from src.infra.persistence.database import Base


# =============================================================================
# In-memory SQLite wired into get_session()
# =============================================================================


@pytest_asyncio.fixture
async def sqlite_db(monkeypatch):
    """Point the global get_session() at a fresh in-memory SQLite database."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    # Import models so every table is registered on Base.metadata.
    import src.infra.persistence.orm_models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db, "_engine", engine)
    monkeypatch.setattr(db, "_session_factory", factory)
    yield
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)
    await engine.dispose()


# =============================================================================
# Phase 2 — GoalStepRepository
# =============================================================================


@pytest.mark.asyncio
async def test_goal_step_repository_lifecycle(sqlite_db):
    from src.infra.persistence.database import get_session
    from src.infra.persistence.repositories.goal_step_repository import (
        GoalStepRepository,
    )

    async with get_session() as session:
        repo = GoalStepRepository(session)
        assert await repo.has_steps(1) is False
        await repo.create_steps(
            1,
            [
                {"expert": "research_expert", "subtask": "find X"},
                {"expert": "math_expert", "subtask": "compute Y"},
            ],
        )

    async with get_session() as session:
        repo = GoalStepRepository(session)
        assert await repo.has_steps(1) is True
        assert await repo.open_step_count(1) == 2
        # Claims happen in seq order.
        step = await repo.claim_next_step(1)
        assert step is not None and step.seq == 0 and step.expert == "research_expert"

    async with get_session() as session:
        repo = GoalStepRepository(session)
        await repo.mark_done(step.id, "found it")
        assert await repo.open_step_count(1) == 1

    async with get_session() as session:
        repo = GoalStepRepository(session)
        step2 = await repo.claim_next_step(1)
        assert step2 is not None and step2.seq == 1
        await repo.mark_done(step2.id, "done")
        assert await repo.open_step_count(1) == 0
        assert await repo.claim_next_step(1) is None


@pytest.mark.asyncio
async def test_goal_step_requeue_and_open_goals(sqlite_db):
    from src.infra.persistence.database import get_session
    from src.infra.persistence.repositories.goal_step_repository import (
        GoalStepRepository,
    )

    async with get_session() as session:
        repo = GoalStepRepository(session)
        await repo.create_steps(7, [{"expert": "generalist", "subtask": "do it"}])
        claimed = await repo.claim_next_step(7)  # now RUNNING
        assert claimed is not None

    # The "crash" — restart scan should requeue the stuck RUNNING step.
    async with get_session() as session:
        repo = GoalStepRepository(session)
        assert await repo.requeue_stuck_running() == 1
        assert 7 in await repo.goal_ids_with_open_steps()


# =============================================================================
# Phase 2 — GoalExecutor
# =============================================================================


class _FakeGoalRepo:
    """Minimal goal repo: tracks a single goal and completion."""

    def __init__(self, goal_id, title, description):
        from src.core.domain.models import Goal, GoalStatus

        self._goal = Goal(id=goal_id, title=title, description=description,
                          status=GoalStatus.ACTIVE)
        self.completed = False

    async def get_by_id(self, goal_id):
        return self._goal if goal_id == self._goal.id else None

    async def mark_complete(self, goal_id):
        self.completed = True
        return self._goal


@pytest.mark.asyncio
async def test_goal_executor_runs_all_steps(sqlite_db):
    from src.app.services.goal_executor import GoalExecutor

    repo = _FakeGoalRepo(11, "Trip plan", "Plan a weekend trip")
    ran: list[tuple[str, str | None]] = []

    async def run_subtask(subtask, thread_id, expert):
        ran.append((subtask, expert))
        return f"did: {subtask}"

    async def decompose(goal_text, max_steps):
        return [
            {"expert": "research_expert", "subtask": "find destinations"},
            {"expert": "generalist", "subtask": "draft itinerary"},
        ]

    ex = GoalExecutor(repo, run_subtask, decompose)
    msg = await ex.start_goal(11, background=False)

    assert "completed" in msg.lower()
    assert repo.completed is True
    assert [e for _, e in ran] == ["research_expert", "generalist"]
    # research_expert routes as an expert; generalist passes None routing target.
    assert ran[0][1] == "research_expert"


@pytest.mark.asyncio
async def test_goal_executor_resume_incomplete(sqlite_db):
    from src.app.services.goal_executor import GoalExecutor
    from src.infra.persistence.database import get_session
    from src.infra.persistence.repositories.goal_step_repository import (
        GoalStepRepository,
    )

    repo = _FakeGoalRepo(22, "Big goal", "")
    # Pre-seed two pending steps as if a previous run had decomposed them.
    async with get_session() as session:
        await GoalStepRepository(session).create_steps(
            22, [{"expert": "generalist", "subtask": "a"}, {"expert": "generalist", "subtask": "b"}]
        )

    done: list[str] = []

    async def run_subtask(subtask, thread_id, expert):
        done.append(subtask)
        return "ok"

    ex = GoalExecutor(repo, run_subtask, decompose=None)
    resumed = await ex.resume_incomplete()
    assert resumed == 1
    # Let the background drive task finish.
    await asyncio.sleep(0.05)
    for _ in range(50):
        if repo.completed:
            break
        await asyncio.sleep(0.02)
    assert repo.completed is True
    assert done == ["a", "b"]


# =============================================================================
# Phase 3 — Watchers + dispatcher
# =============================================================================


@pytest.mark.asyncio
async def test_threshold_watcher_edge_triggered(monkeypatch):
    from src.core.config import get_settings
    from src.runtime.events import EventBus
    from src.runtime.watchers import EVENT_THRESHOLD, ThresholdWatcher

    bus = EventBus()
    received: list[dict] = []
    bus.on(EVENT_THRESHOLD, received.append)

    watcher = ThresholdWatcher(bus, get_settings())
    alerts = ["CPU at 99% (critical)"]
    monkeypatch.setattr(watcher, "_collect_alerts", lambda: list(alerts))

    await watcher._tick()  # first breach → emit
    await watcher._tick()  # unchanged → no emit
    assert len(received) == 1

    alerts.append("Memory at 99% (critical)")
    await watcher._tick()  # changed set → emit again
    assert len(received) == 2

    alerts.clear()
    await watcher._tick()  # recovered → no emit
    assert len(received) == 2


@pytest.mark.asyncio
async def test_file_watcher_detects_new_file(tmp_path):
    from src.runtime.events import EventBus
    from src.runtime.watchers import EVENT_FILE_CHANGED, FileWatcher

    bus = EventBus()
    received: list[dict] = []
    bus.on(EVENT_FILE_CHANGED, received.append)

    watcher = FileWatcher(bus, [str(tmp_path)], interval_seconds=5)
    await watcher._on_start()  # baseline — silent
    assert received == []

    (tmp_path / "new.txt").write_text("hello")
    await watcher._tick()
    assert any(e["change"] == "created" and e["path"].endswith("new.txt") for e in received)


@pytest.mark.asyncio
async def test_event_dispatcher_rate_limits(monkeypatch):
    from src.core.config import Settings
    from src.runtime.watchers import EventDispatcher

    settings = Settings(WATCHER_MAX_EVENTS_PER_HOUR=2, SKIP_CONFIG_VALIDATION=True)
    calls: list[str] = []

    class _Svc:
        async def handle_background_event(self, prompt, ctx):
            calls.append(prompt)

    dispatcher = EventDispatcher(settings, _Svc())
    for _ in range(5):
        await dispatcher._on_threshold({"alerts": ["CPU at 99%"]})
    assert len(calls) == 2  # capped at WATCHER_MAX_EVENTS_PER_HOUR


# =============================================================================
# Phase 4 — In-graph HITL + reflective learning
# =============================================================================


def _build_risky_graph(monkeypatch, llm_responses):
    """Build an AmadeusGraph with a single risky tool and a scripted LLM."""
    from src.app.services.agent_loop import AmadeusGraph
    from src.app.services.tool_registry import ToolRegistry
    from src.infra.tools.base import Tool, ToolCapability, ToolCategory

    async def _danger(**kwargs):
        return "deleted everything"

    risky = Tool(
        name="dangerous_op",
        function=_danger,
        description="A destructive operation",
        category=ToolCategory.FILE_SYSTEM,
        requires_confirmation=True,
        capability=ToolCapability(name="dangerous_op", risk_level="critical",
                                  requires_confirmation=True),
    )
    registry = ToolRegistry()
    registry.register(risky)

    class _FakeExecResult:
        success = True
        result = "deleted everything"
        error_message = None

    class _FakeExecutor:
        async def execute(self, tool, args, **kwargs):
            return _FakeExecResult()

    responses = list(llm_responses)

    async def llm_generate(prompt, **kwargs):
        return responses.pop(0) if responses else '{"tool": "FINISH", "args": {"answer": "done"}}'

    return AmadeusGraph(
        tool_registry=registry,
        tool_executor=_FakeExecutor(),
        llm_generate=llm_generate,
    )


@pytest.mark.asyncio
async def test_ingraph_hitl_pause_and_approve(monkeypatch):
    from src.core.config import get_settings
    from src.core.domain.context import RequestContext
    from src.core.domain.models import PermissionProfile

    monkeypatch.setattr(get_settings(), "ENABLE_INGRAPH_HITL", True)

    # Plan picks the risky tool; reflect then FINISHes.
    graph = _build_risky_graph(
        monkeypatch,
        [
            '{"plan": "run it", "tool": "dangerous_op", "args": {}}',
            '{"tool": "FINISH", "args": {"answer": "all done"}}',
        ],
    )
    ctx = RequestContext(
        request_id="t", session_id="hitl-thread-1", user_id="u",
        permissions=PermissionProfile.SYSTEM_FULL,
    )

    result = await graph.ainvoke(task="clean up", context=ctx, routing_intent="conversational")
    assert result.requires_hitl is True
    assert result.hitl_request_id == "hitl-thread-1"
    assert result.hitl_payload["tool"] == "dangerous_op"

    resumed = await graph.aresume("hitl-thread-1", approved=True)
    assert resumed.requires_hitl is False
    assert "dangerous_op" in resumed.tools_used


@pytest.mark.asyncio
async def test_ingraph_hitl_deny(monkeypatch):
    from src.core.config import get_settings
    from src.core.domain.context import RequestContext
    from src.core.domain.models import PermissionProfile

    monkeypatch.setattr(get_settings(), "ENABLE_INGRAPH_HITL", True)

    graph = _build_risky_graph(
        monkeypatch,
        [
            '{"plan": "run it", "tool": "dangerous_op", "args": {}}',
            '{"tool": "FINISH", "args": {"answer": "stopped"}}',
        ],
    )
    ctx = RequestContext(
        request_id="t", session_id="hitl-thread-2", user_id="u",
        permissions=PermissionProfile.SYSTEM_FULL,
    )

    result = await graph.ainvoke(task="clean up", context=ctx, routing_intent="conversational")
    assert result.requires_hitl is True

    resumed = await graph.aresume("hitl-thread-2", approved=False)
    assert resumed.requires_hitl is False
    # Tool was denied → never recorded as used.
    assert "dangerous_op" not in resumed.tools_used


class _FakeMemory:
    def __init__(self, outcomes=None):
        self.is_enabled = True
        self.stored: list[dict] = []
        self._outcomes = outcomes or []

    async def store(self, session_id, role, text, subtype="interaction", importance=0.5):
        self.stored.append({"text": text, "subtype": subtype})
        return True

    async def retrieve(self, query, top_k=5):
        return self._outcomes


@pytest.mark.asyncio
async def test_reflective_learning_records_outcomes():
    from src.app.services.agent_loop import AmadeusGraph
    from src.app.services.tool_registry import ToolRegistry
    from src.core.domain.context import RequestContext
    from src.core.domain.models import PermissionProfile
    from src.infra.tools.base import ToolExecutor

    mem = _FakeMemory()
    graph = AmadeusGraph(
        tool_registry=ToolRegistry(),
        tool_executor=ToolExecutor(),
        memory_service=mem,
    )
    ctx = RequestContext(
        request_id="t", session_id="s", user_id="u",
        permissions=PermissionProfile.READ_ONLY,
    )
    state = {
        "root_task": "check the weather",
        "observations": ["get_weather: Sunny, 25C", "broken_tool: Error — boom"],
    }
    await graph._record_outcomes(state, ctx)

    subtypes = {s["subtype"] for s in mem.stored}
    assert subtypes == {"outcome"}
    texts = " ".join(s["text"] for s in mem.stored)
    assert "succeeded" in texts and "FAILED" in texts


@pytest.mark.asyncio
async def test_reflective_learning_retrieves_outcomes():
    from src.app.services.agent_loop import AmadeusGraph
    from src.app.services.tool_registry import ToolRegistry
    from src.infra.memory_service import MemoryResult
    from src.infra.tools.base import ToolExecutor

    outcome = MemoryResult(
        session_id="s", role="system", text="[OUTCOME] tool 'x' FAILED for intent: foo",
        timestamp=None, type="memory", subtype="outcome", importance=0.5,
        source="t", distance=0.1,
    )
    chatter = MemoryResult(
        session_id="s", role="user", text="hello there",
        timestamp=None, type="memory", subtype="interaction", importance=0.5,
        source="t", distance=0.1,
    )
    mem = _FakeMemory(outcomes=[outcome, chatter])
    graph = AmadeusGraph(
        tool_registry=ToolRegistry(),
        tool_executor=ToolExecutor(),
        memory_service=mem,
    )
    block = await graph._retrieve_outcomes("foo")
    assert "PAST OUTCOMES" in block
    assert "FAILED" in block
    assert "hello there" not in block  # non-outcome memories excluded
