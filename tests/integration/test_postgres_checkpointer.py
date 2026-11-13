"""
P3: a graph paused on in-graph HITL by one worker can be resumed by another
when both use the Postgres checkpointer (CHECKPOINT_BACKEND=postgres).

Uses the session Postgres testcontainer; skipped without the [scale] extra.
"""

from __future__ import annotations

import pytest


pytest.importorskip("langgraph.checkpoint.postgres.aio")

from tests.unit.test_prompt_safety import _INJECTED_FLOW, _build_graph, _ctx


@pytest.mark.asyncio
async def test_paused_run_resumes_on_another_worker(postgres_container, monkeypatch):
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from src.app.services.amadeus_service import checkpoint_postgres_url
    from src.core.config import get_settings

    monkeypatch.setattr(get_settings(), "ENABLE_INGRAPH_HITL", True)
    url = checkpoint_postgres_url(postgres_container.get_connection_url())

    async with AsyncPostgresSaver.from_conn_string(url) as saver_a:
        await saver_a.setup()
        worker_a, calls_a = _build_graph(_INJECTED_FLOW, [])
        worker_a.set_checkpointer(saver_a)
        paused = await worker_a.ainvoke(
            task="find news",
            context=_ctx("pg-resume-1"),
            routing_intent="conversational",
            allow_orchestration=False,
        )
    assert paused.requires_hitl is True
    assert [name for name, _ in calls_a] == ["web_search"]

    # A different process/worker: new graph, new connection, same database.
    async with AsyncPostgresSaver.from_conn_string(url) as saver_b:
        worker_b, calls_b = _build_graph(_INJECTED_FLOW[1:], [])
        worker_b.set_checkpointer(saver_b)
        resumed = await worker_b.aresume(paused.hitl_request_id, approved=True)

    assert resumed.requires_hitl is False
    assert [name for name, _ in calls_b] == ["add_task"]  # ran on worker B
