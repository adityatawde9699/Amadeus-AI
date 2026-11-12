"""
Repository implementations using SQLAlchemy.

These concrete implementations fulfill the repository interfaces
defined in src/core/interfaces/repositories.py.
"""

from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.domain.models import Task, TaskStatus
from src.core.interfaces.repositories import ITaskRepository
from src.infra.persistence.orm_models import TaskORM, TaskStatusDB


class SQLAlchemyTaskRepository(ITaskRepository):
    """SQLAlchemy implementation of the Task repository.

    ``owner_id`` scopes every read and write to one user's tasks (REST callers).
    ``None`` means unscoped — used by admins and the agent's own task tools.
    """

    def __init__(self, session: AsyncSession, owner_id: int | None = None):
        self._session = session
        self._owner_id = owner_id

    def _scoped(self, query: Select) -> Select:
        if self._owner_id is not None:
            query = query.where(TaskORM.owner_id == self._owner_id)
        return query

    async def _get_orm(self, task_id: int) -> TaskORM | None:
        """Fetch a task, returning None if it belongs to another owner."""
        orm = await self._session.get(TaskORM, task_id)
        if orm is None:
            return None
        if self._owner_id is not None and orm.owner_id != self._owner_id:
            return None
        return orm

    def _orm_to_domain(self, orm: TaskORM) -> Task:
        """Convert ORM model to domain model."""
        return Task(
            id=orm.id,
            content=orm.content,
            status=TaskStatus(orm.status.value),
            created_at=orm.created_at,
            completed_at=orm.completed_at,
        )

    def _domain_to_orm(self, domain: Task) -> TaskORM:
        """Convert domain model to ORM model."""
        return TaskORM(
            id=domain.id,
            content=domain.content,
            status=TaskStatusDB(domain.status.value),
            created_at=domain.created_at,
            completed_at=domain.completed_at,
        )

    async def get_by_id(self, entity_id: int) -> Task | None:
        result = await self._get_orm(entity_id)
        return self._orm_to_domain(result) if result else None

    async def get_all(self, limit: int | None = None, offset: int = 0) -> list[Task]:
        # id breaks ties between rows created within the same clock tick.
        query = self._scoped(select(TaskORM)).order_by(
            TaskORM.created_at.desc(), TaskORM.id.desc()
        )
        if limit:
            query = query.limit(limit)
        if offset:
            query = query.offset(offset)
        result = await self._session.execute(query)
        return [self._orm_to_domain(orm) for orm in result.scalars().all()]

    async def create(self, entity: Task) -> Task:
        orm = TaskORM(
            content=entity.content,
            status=TaskStatusDB(entity.status.value),
            owner_id=self._owner_id,
        )
        self._session.add(orm)
        await self._session.flush()
        return self._orm_to_domain(orm)

    async def update(self, entity: Task) -> Task:
        orm = await self._get_orm(entity.id) if entity.id is not None else None
        if not orm:
            raise ValueError(f"Task with id {entity.id} not found")
        orm.content = entity.content
        orm.status = TaskStatusDB(entity.status.value)
        orm.completed_at = entity.completed_at
        await self._session.flush()
        return self._orm_to_domain(orm)

    async def delete(self, entity_id: int) -> bool:
        orm = await self._get_orm(entity_id)
        if not orm:
            return False
        await self._session.delete(orm)
        await self._session.flush()
        return True

    async def count(self) -> int:
        result = await self._session.execute(self._scoped(select(func.count(TaskORM.id))))
        return int(result.scalar() or 0)

    async def get_by_status(self, status: TaskStatus) -> list[Task]:
        query = (
            self._scoped(select(TaskORM))
            .where(TaskORM.status == TaskStatusDB(status.value))
            .order_by(TaskORM.created_at.desc(), TaskORM.id.desc())
        )
        result = await self._session.execute(query)
        return [self._orm_to_domain(orm) for orm in result.scalars().all()]

    async def get_pending(self) -> list[Task]:
        return await self.get_by_status(TaskStatus.PENDING)

    async def get_completed(self) -> list[Task]:
        return await self.get_by_status(TaskStatus.COMPLETED)

    async def mark_complete(self, task_id: int) -> Task | None:
        orm = await self._get_orm(task_id)
        if not orm:
            return None
        orm.status = TaskStatusDB.COMPLETED
        orm.completed_at = datetime.utcnow()
        await self._session.flush()
        return self._orm_to_domain(orm)

    async def get_summary(self) -> dict:
        total = await self.count()
        pending_count = await self._session.execute(
            self._scoped(select(func.count(TaskORM.id))).where(
                TaskORM.status == TaskStatusDB.PENDING
            )
        )
        completed_count = await self._session.execute(
            self._scoped(select(func.count(TaskORM.id))).where(
                TaskORM.status == TaskStatusDB.COMPLETED
            )
        )
        return {
            "total": total,
            "pending": int(pending_count.scalar() or 0),
            "completed": int(completed_count.scalar() or 0),
        }
