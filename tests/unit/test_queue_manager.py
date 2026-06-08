from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infra.queue.manager import QueueManager


@pytest.mark.asyncio
async def test_initialize_degrades_when_redis_unavailable(monkeypatch):
    async def fail_create_pool(_settings):
        raise ConnectionError("redis down")

    monkeypatch.setattr("src.infra.queue.manager.create_pool", fail_create_pool)

    manager = QueueManager(redis_url="redis://localhost:6379/0")

    await manager.initialize()

    assert manager.is_available is False


@pytest.mark.asyncio
async def test_enqueue_requires_redis_when_pool_unavailable(monkeypatch):
    async def fail_create_pool(_settings):
        raise ConnectionError("redis down")

    monkeypatch.setattr("src.infra.queue.manager.create_pool", fail_create_pool)

    manager = QueueManager(redis_url="redis://localhost:6379/0")
    context = MagicMock()

    with pytest.raises(RuntimeError, match="Background job queue requires Redis"):
        await manager.enqueue_tool("slow_tool", {}, context)


@pytest.mark.asyncio
async def test_enqueue_uses_available_pool(monkeypatch):
    job = MagicMock(job_id="job-123")
    pool = MagicMock()
    pool.enqueue_job = AsyncMock(return_value=job)

    async def create_pool(_settings):
        return pool

    monkeypatch.setattr("src.infra.queue.manager.create_pool", create_pool)

    manager = QueueManager(redis_url="redis://localhost:6379/0")
    context = MagicMock()
    context.request_id = "request-1"
    context.session_id = "session-1"
    context.user_id = "user-1"
    context.permissions.value = "system_full"
    context.memory_scope = "global"
    context.trace_id = "trace-1"

    job_id = await manager.enqueue_tool("slow_tool", {"x": 1}, context)

    assert job_id == "job-123"
    assert manager.is_available is True
    pool.enqueue_job.assert_awaited_once()
