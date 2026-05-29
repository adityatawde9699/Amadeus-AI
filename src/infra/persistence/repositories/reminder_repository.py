"""SQLAlchemy repository implementation for reminders."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.domain.models import Reminder, ReminderStatus
from src.core.interfaces.repositories import IReminderRepository
from src.infra.persistence.orm_models import ReminderORM, ReminderStatusDB


class SQLAlchemyReminderRepository(IReminderRepository):
    """SQLAlchemy implementation of the reminder repository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    def _orm_to_domain(self, orm: ReminderORM) -> Reminder:
        return Reminder(
            id=orm.id,
            title=orm.title,
            time=orm.time,
            description=orm.description or "",
            status=ReminderStatus(orm.status.value),
            created_at=orm.created_at,
        )

    async def get_by_id(self, entity_id: int) -> Reminder | None:
        orm = await self._session.get(ReminderORM, entity_id)
        return self._orm_to_domain(orm) if orm else None

    async def get_all(self, limit: int | None = None, offset: int = 0) -> list[Reminder]:
        query = select(ReminderORM).order_by(ReminderORM.time.asc())
        if limit:
            query = query.limit(limit)
        if offset:
            query = query.offset(offset)
        result = await self._session.execute(query)
        return [self._orm_to_domain(orm) for orm in result.scalars().all()]

    async def create(self, entity: Reminder) -> Reminder:
        orm = ReminderORM(
            title=entity.title,
            time=entity.time,
            description=entity.description,
            status=ReminderStatusDB(entity.status.value),
        )
        self._session.add(orm)
        await self._session.flush()
        return self._orm_to_domain(orm)

    async def update(self, entity: Reminder) -> Reminder:
        orm = await self._session.get(ReminderORM, entity.id)
        if not orm:
            raise ValueError(f"Reminder with id {entity.id} not found")
        orm.title = entity.title
        orm.time = entity.time
        orm.description = entity.description
        orm.status = ReminderStatusDB(entity.status.value)
        await self._session.flush()
        return self._orm_to_domain(orm)

    async def delete(self, entity_id: int) -> bool:
        orm = await self._session.get(ReminderORM, entity_id)
        if not orm:
            return False
        await self._session.delete(orm)
        await self._session.flush()
        return True

    async def count(self) -> int:
        result = await self._session.execute(select(func.count(ReminderORM.id)))
        return int(result.scalar() or 0)

    async def get_by_status(self, status: ReminderStatus) -> list[Reminder]:
        result = await self._session.execute(
            select(ReminderORM)
            .where(ReminderORM.status == ReminderStatusDB(status.value))
            .order_by(ReminderORM.time.asc())
        )
        return [self._orm_to_domain(orm) for orm in result.scalars().all()]

    async def get_active(self) -> list[Reminder]:
        return await self.get_by_status(ReminderStatus.ACTIVE)

    async def get_due(self, as_of: datetime | None = None) -> list[Reminder]:
        reference = as_of or datetime.now(UTC)
        result = await self._session.execute(
            select(ReminderORM)
            .where(
                ReminderORM.status == ReminderStatusDB.ACTIVE,
                ReminderORM.time <= reference,
            )
            .order_by(ReminderORM.time.asc())
        )
        return [self._orm_to_domain(orm) for orm in result.scalars().all()]

    async def get_upcoming(self, hours_ahead: int = 24) -> list[Reminder]:
        now = datetime.now(UTC)
        until = now + timedelta(hours=hours_ahead)
        result = await self._session.execute(
            select(ReminderORM)
            .where(
                ReminderORM.status == ReminderStatusDB.ACTIVE,
                ReminderORM.time >= now,
                ReminderORM.time <= until,
            )
            .order_by(ReminderORM.time.asc())
        )
        return [self._orm_to_domain(orm) for orm in result.scalars().all()]

    async def mark_complete(self, reminder_id: int) -> Reminder | None:
        orm = await self._session.get(ReminderORM, reminder_id)
        if not orm:
            return None
        orm.status = ReminderStatusDB.COMPLETED
        await self._session.flush()
        return self._orm_to_domain(orm)

    async def cancel(self, reminder_id: int) -> Reminder | None:
        orm = await self._session.get(ReminderORM, reminder_id)
        if not orm:
            return None
        orm.status = ReminderStatusDB.CANCELLED
        await self._session.flush()
        return self._orm_to_domain(orm)
