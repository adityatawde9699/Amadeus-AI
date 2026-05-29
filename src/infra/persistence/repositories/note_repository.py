"""SQLAlchemy repository implementation for notes."""

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.domain.models import Note
from src.core.interfaces.repositories import INoteRepository
from src.infra.persistence.orm_models import NoteORM


class SQLAlchemyNoteRepository(INoteRepository):
    """SQLAlchemy implementation of the note repository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    def _orm_to_domain(self, orm: NoteORM) -> Note:
        tags = [tag for tag in (orm.tags or "").split(",") if tag]
        return Note(
            id=orm.id,
            title=orm.title,
            content=orm.content,
            tags=tags,
            created_at=orm.created_at,
            updated_at=orm.updated_at or orm.created_at,
        )

    async def get_by_id(self, entity_id: int) -> Note | None:
        orm = await self._session.get(NoteORM, entity_id)
        return self._orm_to_domain(orm) if orm else None

    async def get_all(self, limit: int | None = None, offset: int = 0) -> list[Note]:
        query = select(NoteORM).order_by(NoteORM.created_at.desc())
        if limit:
            query = query.limit(limit)
        if offset:
            query = query.offset(offset)
        result = await self._session.execute(query)
        return [self._orm_to_domain(orm) for orm in result.scalars().all()]

    async def create(self, entity: Note) -> Note:
        orm = NoteORM(title=entity.title, content=entity.content, tags=entity.tags_str)
        self._session.add(orm)
        await self._session.flush()
        return self._orm_to_domain(orm)

    async def update(self, entity: Note) -> Note:
        orm = await self._session.get(NoteORM, entity.id)
        if not orm:
            raise ValueError(f"Note with id {entity.id} not found")
        orm.title = entity.title
        orm.content = entity.content
        orm.tags = entity.tags_str
        await self._session.flush()
        return self._orm_to_domain(orm)

    async def delete(self, entity_id: int) -> bool:
        orm = await self._session.get(NoteORM, entity_id)
        if not orm:
            return False
        await self._session.delete(orm)
        await self._session.flush()
        return True

    async def count(self) -> int:
        result = await self._session.execute(select(func.count(NoteORM.id)))
        return int(result.scalar() or 0)

    async def search(self, query: str) -> list[Note]:
        pattern = f"%{query}%"
        result = await self._session.execute(
            select(NoteORM)
            .where(or_(NoteORM.title.ilike(pattern), NoteORM.content.ilike(pattern)))
            .order_by(NoteORM.created_at.desc())
        )
        return [self._orm_to_domain(orm) for orm in result.scalars().all()]

    async def get_by_tag(self, tag: str) -> list[Note]:
        result = await self._session.execute(
            select(NoteORM)
            .where(NoteORM.tags.ilike(f"%{tag}%"))
            .order_by(NoteORM.created_at.desc())
        )
        return [self._orm_to_domain(orm) for orm in result.scalars().all()]

    async def get_recent(self, limit: int = 10) -> list[Note]:
        return await self.get_all(limit=limit)

    async def get_summary(self) -> dict:
        return {"total": await self.count()}
