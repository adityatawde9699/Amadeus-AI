"""
P3: multi-worker shared state — Redis-backed HITL confirmations, Redis auth
rate limiting, and checkpointer backend selection.

"Two workers" are simulated as two callback instances sharing one fake Redis
server: one waits on a confirmation, the other lists / resolves it.
"""

from __future__ import annotations

import asyncio

import pytest


fakeredis = pytest.importorskip("fakeredis")


@pytest.fixture
def server():
    return fakeredis.FakeServer()


def _client(server):
    return fakeredis.FakeAsyncRedis(server=server, decode_responses=True)


def _cb(server, timeout=5):
    from src.infra.tools.confirmation import RedisConfirmationCallback

    return RedisConfirmationCallback(_client(server), timeout_seconds=timeout)


async def _wait_for_pending(cb, request_id, tries=100):
    for _ in range(tries):
        if await cb.aget_pending(request_id):
            return
        await asyncio.sleep(0.01)
    raise AssertionError("confirmation never became visible")


async def _request(worker, request_id, owner="42"):
    from src.infra.tools.confirmation import confirmation_owner

    token = confirmation_owner.set(owner)
    try:
        return await worker.request_approval("delete_file", {"path": "/x"}, request_id, "rm /x")
    finally:
        confirmation_owner.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", [True, False])
async def test_decision_from_another_worker_reaches_waiter(server, decision):
    worker_a, worker_b = _cb(server), _cb(server)
    waiter = asyncio.create_task(_request(worker_a, "req-1"))
    await _wait_for_pending(worker_b, "req-1")

    pending = await worker_b.aget_pending("req-1")
    assert pending.tool_name == "delete_file"
    assert worker_b.is_owner(pending, "42") and not worker_b.is_owner(pending, "7")
    assert [p["request_id"] for p in await worker_b.alist_pending("42")] == ["req-1"]
    assert await worker_b.alist_pending("7") == []

    assert await worker_b.aapprove("req-1", decision) is True
    assert await asyncio.wait_for(waiter, 2) is decision
    # cleaned up once resolved
    assert await worker_b.aget_pending("req-1") is None
    assert await worker_b.alist_pending() == []


@pytest.mark.asyncio
async def test_timeout_denies_and_unknown_ids_are_rejected(server):
    worker = _cb(server, timeout=1)
    assert await _request(worker, "req-2") is False  # nobody answered
    assert await worker.aapprove("req-2", True) is False  # expired
    assert await worker.aapprove("never-existed", True) is False


@pytest.mark.asyncio
async def test_redis_failure_fails_closed():
    from src.infra.tools.confirmation import RedisConfirmationCallback

    class _Broken:
        def pipeline(self, **_):
            raise ConnectionError("redis down")

    assert await RedisConfirmationCallback(_Broken(), 1).request_approval("t", {}, "r") is False


def test_sync_accessors_refuse_on_redis_backend(server):
    cb = _cb(server)
    with pytest.raises(NotImplementedError):
        cb.approve("x", True)


@pytest.mark.asyncio
async def test_factory_selects_backend_and_fails_fast_when_unreachable():
    from src.infra.tools.confirmation import (
        APIConfirmationCallback,
        RedisConfirmationCallback,
        create_api_confirmation_callback,
    )

    cb = await create_api_confirmation_callback("memory", None)
    assert type(cb) is APIConfirmationCallback
    assert not isinstance(cb, RedisConfirmationCallback)
    with pytest.raises(RuntimeError, match="unreachable"):
        await create_api_confirmation_callback("redis", "redis://127.0.0.1:1/0")


@pytest.mark.asyncio
async def test_in_memory_callback_async_accessors_match_sync():
    from src.infra.tools.confirmation import APIConfirmationCallback

    cb = APIConfirmationCallback(timeout_seconds=5)
    waiter = asyncio.create_task(_request(cb, "req-3"))
    await _wait_for_pending(cb, "req-3")
    assert (await cb.alist_pending("42"))[0]["request_id"] == "req-3"
    assert await cb.aapprove("req-3", True) is True
    assert await asyncio.wait_for(waiter, 2) is True


# =============================================================================
# Auth rate limiter across workers
# =============================================================================


def _app(server, monkeypatch, limit=3):
    from fastapi import FastAPI

    from src.api.middleware import rate_limit
    from src.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "SHARED_STATE_BACKEND", "redis")
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_REQUESTS", limit)
    monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_WINDOW_SECONDS", 60)
    monkeypatch.setattr(
        rate_limit.RateLimitMiddleware, "_redis_client", lambda self: _client(server)
    )
    app = FastAPI()
    app.add_middleware(rate_limit.RateLimitMiddleware)

    @app.post("/api/v1/auth/jwt/login")
    async def login():
        return {"ok": True}

    return app


def test_auth_limit_is_shared_between_workers(server, monkeypatch):
    from fastapi.testclient import TestClient

    worker_a = TestClient(_app(server, monkeypatch))
    worker_b = TestClient(_app(server, monkeypatch))
    codes = [
        c.post("/api/v1/auth/jwt/login").status_code
        for c in (worker_a, worker_b, worker_a, worker_b)
    ]
    assert codes == [200, 200, 200, 429]  # limit 3 holds across both workers


def test_auth_limit_falls_back_to_process_window_when_redis_down(monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.middleware import rate_limit

    app = _app(None, monkeypatch, limit=2)

    class _Down:
        def pipeline(self, **_):
            raise ConnectionError("redis down")

    monkeypatch.setattr(rate_limit.RateLimitMiddleware, "_redis_client", lambda self: _Down())
    client = TestClient(app)
    codes = [client.post("/api/v1/auth/jwt/login").status_code for _ in range(3)]
    assert codes == [200, 200, 429]  # degraded to per-process, never unlimited


# =============================================================================
# Checkpointer backend selection
# =============================================================================


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql+asyncpg://u:p@h:5432/db", "postgresql://u:p@h:5432/db"),
        ("postgres://u@h/db", "postgresql://u@h/db"),
        ("postgresql://u@h/db?sslmode=require", "postgresql://u@h/db?sslmode=require"),
    ],
)
def test_checkpoint_url_normalised_for_psycopg(url, expected):
    from src.app.services.amadeus_service import checkpoint_postgres_url

    assert checkpoint_postgres_url(url) == expected


def test_checkpoint_url_rejects_non_postgres():
    from src.app.services.amadeus_service import checkpoint_postgres_url

    with pytest.raises(RuntimeError, match="PostgreSQL URL"):
        checkpoint_postgres_url("sqlite+aiosqlite:///x.db")
