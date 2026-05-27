"""
Goal repository implementation using SQLAlchemy.
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.domain.models import Goal, GoalStatus
from src.core.interfaces.repositories import IGoalRepository
from src.infra.persistence.orm_models import GoalORM, GoalStatusDB


class SQLAlchemyGoalRepository(IGoalRepository):
    """SQLAlchemy implementation of the Goal repository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    def _orm_to_domain(self, orm: GoalORM) -> Goal:
        """Convert ORM model to domain model."""
        return Goal(
            id=orm.id,
            title=orm.title,
            description=orm.description,
            status=GoalStatus(orm.status.value),
            target_date=orm.target_date,
            created_at=orm.created_at,
            completed_at=orm.completed_at,
            parent_goal_id=orm.parent_goal_id,
        )

    def _domain_to_orm(self, domain: Goal) -> GoalORM:
        """Convert domain model to ORM model."""
        return GoalORM(
            id=domain.id,
            title=domain.title,
            description=domain.description,
            status=GoalStatusDB(domain.status.value),
            target_date=domain.target_date,
            created_at=domain.created_at,
            completed_at=domain.completed_at,
            parent_goal_id=domain.parent_goal_id,
        )

    async def get_by_id(self, entity_id: int) -> Goal | None:
        result = await self._session.get(GoalORM, entity_id)
        return self._orm_to_domain(result) if result else None

    async def get_all(self, limit: int | None = None, offset: int = 0) -> list[Goal]:
        query = select(GoalORM).order_by(GoalORM.created_at.desc())
        if limit:
            query = query.limit(limit)
        if offset:
            query = query.offset(offset)
        result = await self._session.execute(query)
        return [self._orm_to_domain(orm) for orm in result.scalars().all()]

    async def create(self, entity: Goal) -> Goal:
        orm = GoalORM(
            title=entity.title,
            description=entity.description,
            status=GoalStatusDB(entity.status.value),
            target_date=entity.target_date,
            parent_goal_id=entity.parent_goal_id,
        )
        self._session.add(orm)
        await self._session.flush()
        return self._orm_to_domain(orm)

    async def update(self, entity: Goal) -> Goal:
        orm = await self._session.get(GoalORM, entity.id)
        if not orm:
            raise ValueError(f"Goal with id {entity.id} not found")
        orm.title = entity.title
        orm.description = entity.description
        orm.status = GoalStatusDB(entity.status.value)
        orm.target_date = entity.target_date
        orm.completed_at = entity.completed_at
        orm.parent_goal_id = entity.parent_goal_id
        await self._session.flush()
        return self._orm_to_domain(orm)

    async def delete(self, entity_id: int) -> bool:
        orm = await self._session.get(GoalORM, entity_id)
        if not orm:
            return False
        await self._session.delete(orm)
        await self._session.flush()
        return True

    async def count(self) -> int:
        result = await self._session.execute(select(func.count(GoalORM.id)))
        return int(result.scalar() or 0)

    async def get_by_status(self, status: GoalStatus) -> list[Goal]:
        query = (
            select(GoalORM)
            .where(GoalORM.status == GoalStatusDB(status.value))
            .order_by(GoalORM.created_at.desc())
        )
        result = await self._session.execute(query)
        return [self._orm_to_domain(orm) for orm in result.scalars().all()]

    async def get_active(self) -> list[Goal]:
        return await self.get_by_status(GoalStatus.ACTIVE)

    async def get_completed(self) -> list[Goal]:
        return await self.get_by_status(GoalStatus.COMPLETED)

    async def mark_complete(self, goal_id: int) -> Goal | None:
        orm = await self._session.get(GoalORM, goal_id)
        if not orm:
            return None
        orm.status = GoalStatusDB.COMPLETED
        orm.completed_at = datetime.utcnow()
        await self._session.flush()
        return self._orm_to_domain(orm)
