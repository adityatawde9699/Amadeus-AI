"""
SQLAlchemy repository for Pomodoro sessions.

Implements IPomodoroRepository using async SQLAlchemy sessions.
Follows the same pattern as SQLAlchemyTaskRepository.
"""

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.domain.models import PomodoroSession, PomodoroState
from src.core.interfaces.repositories import IPomodoroRepository
from src.infra.persistence.orm_models import PomodoroSessionORM, PomodoroStateDB


def _orm_to_domain(orm: PomodoroSessionORM) -> PomodoroSession:
    """Convert ORM row to domain model."""
    return PomodoroSession(
        id=orm.id,
        state=PomodoroState(orm.state.value),
        task_description=orm.task_description or "",
        started_at=orm.started_at,
        completed_at=orm.completed_at,
        work_duration_minutes=orm.work_duration_minutes,
        short_break_minutes=orm.short_break_minutes,
        long_break_minutes=orm.long_break_minutes,
        cycles_completed=orm.cycles_completed,
        created_at=orm.created_at,
    )


class SQLAlchemyPomodoroRepository(IPomodoroRepository):
    """Concrete async SQLAlchemy implementation of IPomodoroRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, session_model: PomodoroSession) -> PomodoroSession:
        """Insert a new Pomodoro session and return the persisted record."""
        orm = PomodoroSessionORM(
            state=PomodoroStateDB(session_model.state.value),
            task_description=session_model.task_description,
            work_duration_minutes=session_model.work_duration_minutes,
            short_break_minutes=session_model.short_break_minutes,
            long_break_minutes=session_model.long_break_minutes,
            cycles_completed=0,
        )
        self._session.add(orm)
        await self._session.flush()
        return _orm_to_domain(orm)

    async def get_by_id(self, session_id: int) -> PomodoroSession | None:
        """Fetch a single Pomodoro session by ID."""
        orm = await self._session.get(PomodoroSessionORM, session_id)
        return _orm_to_domain(orm) if orm else None

    async def get_active(self) -> PomodoroSession | None:
        """Return the most recent session that is not idle/completed."""
        active_states = [
            PomodoroStateDB.WORKING,
            PomodoroStateDB.SHORT_BREAK,
            PomodoroStateDB.LONG_BREAK,
            PomodoroStateDB.PAUSED,
        ]
        result = await self._session.execute(
            select(PomodoroSessionORM)
            .where(PomodoroSessionORM.state.in_(active_states))
            .order_by(PomodoroSessionORM.started_at.desc())
            .limit(1)
        )
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def update_state(
        self,
        session_id: int,
        new_state: PomodoroState,
        cycles_completed: int | None = None,
    ) -> PomodoroSession | None:
        """Transition a Pomodoro session to a new state."""
        orm = await self._session.get(PomodoroSessionORM, session_id)
        if not orm:
            return None
        orm.state = PomodoroStateDB(new_state.value)
        if new_state == PomodoroState.WORKING and orm.started_at is None:
            orm.started_at = datetime.now(timezone.utc)
        if new_state == PomodoroState.COMPLETED:
            orm.completed_at = datetime.now(timezone.utc)
        if cycles_completed is not None:
            orm.cycles_completed = cycles_completed
        await self._session.flush()
        return _orm_to_domain(orm)

    async def list_recent(self, limit: int = 10) -> list[PomodoroSession]:
        """Return the N most recent Pomodoro sessions."""
        result = await self._session.execute(
            select(PomodoroSessionORM)
            .order_by(PomodoroSessionORM.created_at.desc())
            .limit(limit)
        )
        return [_orm_to_domain(orm) for orm in result.scalars().all()]

    async def count_completed_today(self) -> int:
        """Count Pomodoro cycles completed today (UTC)."""
        from sqlalchemy import func, and_
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        result = await self._session.execute(
            select(func.sum(PomodoroSessionORM.cycles_completed)).where(
                and_(
                    PomodoroSessionORM.state == PomodoroStateDB.COMPLETED,
                    PomodoroSessionORM.completed_at >= today_start,
                )
            )
        )
        return int(result.scalar() or 0)
