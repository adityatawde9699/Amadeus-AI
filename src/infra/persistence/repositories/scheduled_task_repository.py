"""
Repository for durable agent-scheduled tasks.

Backs the restart-safe scheduler: the ``schedule_future_task`` tool enqueues
rows here, and the scheduler sweeper atomically claims due rows and dispatches
them. Methods operate on a caller-supplied :class:`AsyncSession` (the same
``get_session()`` pattern used by the other repositories), and return detached
plain dataclasses so callers can use the data after the session closes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.infra.persistence.orm_models import ScheduledTaskORM, ScheduledTaskStatusDB


@dataclass(frozen=True)
class DueTask:
    """A claimed, ready-to-run scheduled task (detached from the session)."""

    id: int
    prompt: str
    session_id: str


class ScheduledTaskRepository:
    """SQLAlchemy-backed store for durable scheduled tasks."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, prompt: str, session_id: str, run_at: datetime) -> int:
        orm = ScheduledTaskORM(
            prompt=prompt,
            session_id=session_id or "background",
            run_at=run_at,
            status=ScheduledTaskStatusDB.PENDING,
        )
        self._session.add(orm)
        await self._session.flush()
        return orm.id

    async def claim_due(self, now: datetime | None = None, limit: int = 10) -> list[DueTask]:
        """Atomically claim due PENDING tasks, marking them RUNNING.

        Marking RUNNING inside the same transaction that selects them prevents a
        second sweeper tick (or a concurrent worker) from re-dispatching the
        same task.
        """
        now = now or datetime.now(UTC).replace(tzinfo=None)
        query = (
            select(ScheduledTaskORM)
            .where(
                ScheduledTaskORM.status == ScheduledTaskStatusDB.PENDING,
                ScheduledTaskORM.run_at <= now,
            )
            .order_by(ScheduledTaskORM.run_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(query)
        rows = list(result.scalars().all())

        claimed: list[DueTask] = []
        for orm in rows:
            orm.status = ScheduledTaskStatusDB.RUNNING
            orm.attempts = (orm.attempts or 0) + 1
            claimed.append(DueTask(id=orm.id, prompt=orm.prompt, session_id=orm.session_id))
        await self._session.flush()
        return claimed

    async def mark_done(self, task_id: int) -> None:
        await self._session.execute(
            update(ScheduledTaskORM)
            .where(ScheduledTaskORM.id == task_id)
            .values(
                status=ScheduledTaskStatusDB.DONE,
                executed_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )

    async def mark_failed(self, task_id: int, error: str) -> None:
        await self._session.execute(
            update(ScheduledTaskORM)
            .where(ScheduledTaskORM.id == task_id)
            .values(
                status=ScheduledTaskStatusDB.FAILED,
                last_error=error[:2000],
                executed_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )

    async def cancel(self, task_id: int) -> bool:
        orm = await self._session.get(ScheduledTaskORM, task_id)
        if not orm or orm.status != ScheduledTaskStatusDB.PENDING:
            return False
        orm.status = ScheduledTaskStatusDB.CANCELLED
        await self._session.flush()
        return True

    async def count_pending(self) -> int:
        result = await self._session.execute(
            select(func.count(ScheduledTaskORM.id)).where(
                ScheduledTaskORM.status == ScheduledTaskStatusDB.PENDING
            )
        )
        return int(result.scalar() or 0)

    async def requeue_stuck_running(self) -> int:
        """Reset RUNNING rows to PENDING (e.g. after a crash mid-dispatch)."""
        result = await self._session.execute(
            update(ScheduledTaskORM)
            .where(ScheduledTaskORM.status == ScheduledTaskStatusDB.RUNNING)
            .values(status=ScheduledTaskStatusDB.PENDING)
        )
        return int(result.rowcount or 0)
