"""
Durable, restart-safe task scheduler.

Replaces the previous in-memory stub. Scheduled tasks are persisted to the
``scheduled_tasks`` table (see :class:`ScheduledTaskORM`); a background sweeper
polls for due rows, claims them atomically, and dispatches each through an
injected coroutine. Because the queue lives in the database, a daemon restart
re-loads pending work instead of losing it.

Wiring:
  * ``schedule_future_task`` tool → :func:`enqueue_task` (writes a PENDING row)
  * :class:`AmadeusRuntime` → ``scheduler.start(dispatch)`` / ``scheduler.stop()``
    where ``dispatch(prompt, session_id)`` routes back into the agent loop.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from src.infra.persistence.database import get_session
from src.infra.persistence.repositories.scheduled_task_repository import (
    ScheduledTaskRepository,
)


logger = logging.getLogger(__name__)

# dispatch(prompt, session_id) -> awaitable
DispatchFn = Callable[[str, str], Awaitable[None]]


async def enqueue_task(
    prompt: str,
    session_id: str = "background",
    *,
    delay_minutes: float = 0.0,
    run_at: datetime | None = None,
) -> int:
    """Persist a scheduled task and return its id.

    Decoupled from the running scheduler on purpose: the row is the durable
    hand-off, so enqueuing works even before the sweeper has started (e.g. during
    tool registration), and survives a restart.
    """
    if run_at is None:
        run_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=delay_minutes)
    async with get_session() as session:
        repo = ScheduledTaskRepository(session)
        return await repo.create(prompt=prompt, session_id=session_id, run_at=run_at)


class TaskScheduler:
    """Single entry point for durable background work.

    The sweeper runs only while the daemon is up; the queue itself is the
    database, so this object holds no irreplaceable state.
    """

    def __init__(self, poll_interval_seconds: float = 20.0, batch_size: int = 10) -> None:
        self._poll_interval = poll_interval_seconds
        self._batch_size = batch_size
        self._dispatch: DispatchFn | None = None
        self._sweeper: asyncio.Task | None = None
        self._stopped = asyncio.Event()

    async def schedule(
        self,
        prompt: str,
        session_id: str = "background",
        *,
        delay_minutes: float = 0.0,
        run_at: datetime | None = None,
    ) -> int:
        """Enqueue a durable task; returns its id."""
        return await enqueue_task(
            prompt, session_id, delay_minutes=delay_minutes, run_at=run_at
        )

    async def cancel(self, task_id: int) -> bool:
        async with get_session() as session:
            return await ScheduledTaskRepository(session).cancel(task_id)

    async def start(self, dispatch: DispatchFn) -> None:
        """Begin sweeping for due tasks and dispatching them."""
        if self._sweeper is not None:
            logger.debug("TaskScheduler already started")
            return
        self._dispatch = dispatch
        self._stopped.clear()

        # Recover any rows left RUNNING by a previous crash mid-dispatch.
        try:
            async with get_session() as session:
                requeued = await ScheduledTaskRepository(session).requeue_stuck_running()
            if requeued:
                logger.info("Requeued %d scheduled task(s) stuck in RUNNING", requeued)
        except Exception:
            logger.exception("Failed to requeue stuck scheduled tasks")

        self._sweeper = asyncio.create_task(self._sweep_loop())
        logger.info("Durable TaskScheduler started (poll=%.0fs)", self._poll_interval)

    async def stop(self) -> None:
        self._stopped.set()
        if self._sweeper is not None:
            self._sweeper.cancel()
            try:
                await self._sweeper
            except asyncio.CancelledError:
                pass
            self._sweeper = None
        logger.info("Durable TaskScheduler stopped")

    async def _sweep_loop(self) -> None:
        while not self._stopped.is_set():
            try:
                await self._sweep_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scheduler sweep failed")
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self._poll_interval)
            except TimeoutError:
                pass

    async def _sweep_once(self) -> None:
        if self._dispatch is None:
            return
        # Claim due tasks in one short transaction, then dispatch outside it.
        async with get_session() as session:
            claimed = await ScheduledTaskRepository(session).claim_due(limit=self._batch_size)
        if not claimed:
            return
        logger.info("Scheduler dispatching %d due task(s)", len(claimed))
        for task in claimed:
            try:
                await self._dispatch(task.prompt, task.session_id)
                async with get_session() as session:
                    await ScheduledTaskRepository(session).mark_done(task.id)
            except Exception as exc:
                logger.exception("Scheduled task %d dispatch failed", task.id)
                async with get_session() as session:
                    await ScheduledTaskRepository(session).mark_failed(task.id, str(exc))
