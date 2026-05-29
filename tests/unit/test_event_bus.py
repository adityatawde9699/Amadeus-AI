from __future__ import annotations

import pytest

from src.runtime.events import EventBus


@pytest.mark.asyncio
async def test_emit_calls_sync_and_async_subscribers():
    bus = EventBus()
    seen: list[tuple[str, int]] = []

    def sync_handler(payload: dict):
        seen.append(("sync", payload["value"]))

    async def async_handler(payload: dict):
        seen.append(("async", payload["value"]))

    bus.on("task.created", sync_handler)
    bus.on("task.created", async_handler)

    await bus.emit("task.created", {"value": 7})

    assert sorted(seen) == [("async", 7), ("sync", 7)]


@pytest.mark.asyncio
async def test_emit_isolates_handler_failures():
    bus = EventBus()
    seen: list[str] = []

    def failing_handler(payload: dict):
        raise RuntimeError("boom")

    async def healthy_handler(payload: dict):
        seen.append(payload["status"])

    bus.on("health.changed", failing_handler)
    bus.on("health.changed", healthy_handler)

    await bus.emit("health.changed", {"status": "ok"})

    assert seen == ["ok"]


@pytest.mark.asyncio
async def test_emit_with_no_subscribers_is_noop():
    bus = EventBus()

    await bus.emit("missing.event", {"anything": True})
