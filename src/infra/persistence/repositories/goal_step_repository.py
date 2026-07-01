"""
Repository for durable goal execution steps (Phase 2 — long-horizon goals).

Backs :class:`GoalExecutor`: a goal is decomposed into ordered ``goal_steps``
rows, which the executor claims and runs one at a time. Methods operate on a
caller-supplied :class:`AsyncSession` (the same ``get_session()`` pattern used
by the other repositories) and return detached plain dataclasses so callers can
use the data after the session closes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from src.infra.persistence.orm_models import GoalStepORM, ScheduledTaskStatusDB


if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class GoalStep:
    """A goal execution step detached from the session."""

    id: int
    goal_id: int
    seq: int
    expert: str | None
    subtask: str
    status: str
    result: str | None


class GoalStepRepository:
    """SQLAlchemy-backed store for durable goal execution steps."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_dataclass(orm: GoalStepORM) -> GoalStep:
        return GoalStep(
            id=orm.id,
            goal_id=orm.goal_id,
            seq=orm.seq,
            expert=orm.expert,
            subtask=orm.subtask,
            status=orm.status.value,
            result=orm.result,
        )

    async def create_steps(
        self, goal_id: int, steps: list[dict]
    ) -> list[GoalStep]:
        """Persist an ordered list of ``{expert, subtask}`` steps for a goal."""
        created: list[GoalStepORM] = []
        for seq, step in enumerate(steps):
            orm = GoalStepORM(
                goal_id=goal_id,
                seq=seq,
                expert=(step.get("expert") or None),
                subtask=str(step.get("subtask", "")).strip(),
                status=ScheduledTaskStatusDB.PENDING,
            )
            self._session.add(orm)
            created.append(orm)
        await self._session.flush()
        return [self._to_dataclass(o) for o in created]

    async def has_steps(self, goal_id: int) -> bool:
        result = await self._session.execute(
            select(func.count(GoalStepORM.id)).where(GoalStepORM.goal_id == goal_id)
        )
        return int(result.scalar() or 0) > 0

    async def claim_next_step(self, goal_id: int) -> GoalStep | None:
        """Atomically claim the lowest-seq PENDING step, marking it RUNNING.

        Marking RUNNING in the same transaction that selects it prevents a
        concurrent resume from running the same step twice.
        """
        query = (
            select(GoalStepORM)
            .where(
                GoalStepORM.goal_id == goal_id,
                GoalStepORM.status == ScheduledTaskStatusDB.PENDING,
            )
            .order_by(GoalStepORM.seq.asc())
            .limit(1)
        )
        result = await self._session.execute(query)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        orm.status = ScheduledTaskStatusDB.RUNNING
        orm.attempts = (orm.attempts or 0) + 1
        await self._session.flush()
        return self._to_dataclass(orm)

    async def mark_done(self, step_id: int, result: str) -> None:
        orm = await self._session.get(GoalStepORM, step_id)
        if orm is None:
            return
        orm.status = ScheduledTaskStatusDB.DONE
        orm.result = (result or "")[:8000]
        orm.completed_at = datetime.now(UTC).replace(tzinfo=None)
        await self._session.flush()

    async def mark_failed(self, step_id: int, error: str) -> None:
        orm = await self._session.get(GoalStepORM, step_id)
        if orm is None:
            return
        orm.status = ScheduledTaskStatusDB.FAILED
        orm.last_error = (error or "")[:2000]
        orm.completed_at = datetime.now(UTC).replace(tzinfo=None)
        await self._session.flush()

    async def requeue_stuck_running(self, goal_id: int | None = None) -> int:
        """Reset RUNNING steps to PENDING (e.g. after a crash mid-step)."""
        query = select(GoalStepORM).where(
            GoalStepORM.status == ScheduledTaskStatusDB.RUNNING
        )
        if goal_id is not None:
            query = query.where(GoalStepORM.goal_id == goal_id)
        result = await self._session.execute(query)
        rows = list(result.scalars().all())
        for orm in rows:
            orm.status = ScheduledTaskStatusDB.PENDING
        await self._session.flush()
        return len(rows)

    async def open_step_count(self, goal_id: int) -> int:
        """Count steps that are neither DONE nor CANCELLED (i.e. still pending work)."""
        result = await self._session.execute(
            select(func.count(GoalStepORM.id)).where(
                GoalStepORM.goal_id == goal_id,
                GoalStepORM.status.notin_(
                    (ScheduledTaskStatusDB.DONE, ScheduledTaskStatusDB.CANCELLED)
                ),
            )
        )
        return int(result.scalar() or 0)

    async def all_steps(self, goal_id: int) -> list[GoalStep]:
        query = (
            select(GoalStepORM)
            .where(GoalStepORM.goal_id == goal_id)
            .order_by(GoalStepORM.seq.asc())
        )
        result = await self._session.execute(query)
        return [self._to_dataclass(o) for o in result.scalars().all()]

    async def goal_ids_with_open_steps(self) -> list[int]:
        """Distinct goal ids that still have non-terminal steps (for resume)."""
        query = (
            select(GoalStepORM.goal_id)
            .where(
                GoalStepORM.status.notin_(
                    (ScheduledTaskStatusDB.DONE, ScheduledTaskStatusDB.CANCELLED)
                )
            )
            .distinct()
        )
        result = await self._session.execute(query)
        return [int(gid) for gid in result.scalars().all()]
