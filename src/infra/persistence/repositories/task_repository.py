"""
Repository implementations using SQLAlchemy.

These concrete implementations fulfill the repository interfaces
defined in src/core/interfaces/repositories.py.
"""

from datetime import datetime, timedelta
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.domain.models import Task, TaskStatus
from src.core.interfaces.repositories import ITaskRepository
from src.infra.persistence.orm_models import TaskORM, TaskStatusDB


class SQLAlchemyTaskRepository(ITaskRepository):
    """SQLAlchemy implementation of the Task repository."""
    
    def __init__(self, session: AsyncSession):
        self._session = session
    
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
        result = await self._session.get(TaskORM, entity_id)
        return self._orm_to_domain(result) if result else None
    
    async def get_all(self, limit: int | None = None, offset: int = 0) -> list[Task]:
        query = select(TaskORM).order_by(TaskORM.created_at.desc())
        if limit:
            query = query.limit(limit)
        if offset:
            query = query.offset(offset)
        result = await self._session.execute(query)
        return [self._orm_to_domain(orm) for orm in result.scalars().all()]
    
    async def create(self, entity: Task) -> Task:
        orm = self._domain_to_orm(entity)
        orm.id = None  # Ensure ID is auto-generated
        self._session.add(orm)
        await self._session.flush()
        return self._orm_to_domain(orm)
    
    async def update(self, entity: Task) -> Task:
        orm = await self._session.get(TaskORM, entity.id)
        if not orm:
            raise ValueError(f"Task with id {entity.id} not found")
        orm.content = entity.content
        orm.status = TaskStatusDB(entity.status.value)
        orm.completed_at = entity.completed_at
        await self._session.flush()
        return self._orm_to_domain(orm)
    
    async def delete(self, entity_id: int) -> bool:
        orm = await self._session.get(TaskORM, entity_id)
        if not orm:
            return False
        await self._session.delete(orm)
        await self._session.flush()
        return True
    
    async def count(self) -> int:
        result = await self._session.execute(select(func.count(TaskORM.id)))
        return result.scalar() or 0
    
    async def get_by_status(self, status: TaskStatus) -> list[Task]:
        query = select(TaskORM).where(
            TaskORM.status == TaskStatusDB(status.value)
        ).order_by(TaskORM.created_at.desc())
        result = await self._session.execute(query)
        return [self._orm_to_domain(orm) for orm in result.scalars().all()]
    
    async def get_pending(self) -> list[Task]:
        return await self.get_by_status(TaskStatus.PENDING)
    
    async def get_completed(self) -> list[Task]:
        return await self.get_by_status(TaskStatus.COMPLETED)
    
    async def mark_complete(self, task_id: int) -> Task | None:
        orm = await self._session.get(TaskORM, task_id)
        if not orm:
            return None
        orm.status = TaskStatusDB.COMPLETED
        orm.completed_at = datetime.utcnow()
        await self._session.flush()
        return self._orm_to_domain(orm)
    
    async def get_summary(self) -> dict:
        total = await self.count()
        pending_count = await self._session.execute(
            select(func.count(TaskORM.id)).where(
                TaskORM.status == TaskStatusDB.PENDING
            )
        )
        completed_count = await self._session.execute(
            select(func.count(TaskORM.id)).where(
                TaskORM.status == TaskStatusDB.COMPLETED
            )
        )
        return {
            "total": total,
            "pending": pending_count.scalar() or 0,
            "completed": completed_count.scalar() or 0,
        }
