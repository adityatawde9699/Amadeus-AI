"""
SQLAlchemy implementation of the Knowledge Graph repository.
"""

import logging
from typing import Any, List, Optional, Dict

from sqlalchemy import select, and_, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.interfaces.repositories import IKnowledgeGraphRepository
from src.infra.persistence.orm_models import EntityORM, RelationshipORM

logger = logging.getLogger(__name__)

class SQLKnowledgeGraphRepository(IKnowledgeGraphRepository):
    """
    Handles persistence for the Knowledge Graph (Entities and Relationships).
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_entity(self, name: str, entity_type: str | None = None, description: str | None = None) -> int:
        """Create or update an entity by name."""
        try:
            # Check if exists
            stmt = select(EntityORM).where(EntityORM.name == name)
            result = await self.session.execute(stmt)
            entity = result.scalars().first()

            if entity:
                # Update if new info provided
                if entity_type:
                    entity.entity_type = entity_type
                if description:
                    entity.description = description
                await self.session.commit()
                return entity.id

            # Create new
            new_entity = EntityORM(
                name=name,
                entity_type=entity_type or "unknown",
                description=description or ""
            )
            self.session.add(new_entity)
            await self.session.flush() # Get ID without full commit
            await self.session.commit()
            return new_entity.id
        except Exception as e:
            logger.error(f"Error upserting entity '{name}': {e}")
            await self.session.rollback()
            raise

    async def add_relationship(self, subject_id: int, predicate: str, object_id: int) -> None:
        """Add or strengthen a relationship."""
        try:
            # Check if relationship already exists
            stmt = select(RelationshipORM).where(and_(
                RelationshipORM.subject_id == subject_id,
                RelationshipORM.predicate == predicate,
                RelationshipORM.object_id == object_id
            ))
            result = await self.session.execute(stmt)
            rel = result.scalars().first()

            if rel:
                # Strengthen
                rel.strength += 1
            else:
                # Create new
                new_rel = RelationshipORM(
                    subject_id=subject_id,
                    predicate=predicate,
                    object_id=object_id,
                    strength=1
                )
                self.session.add(new_rel)
            
            await self.session.commit()
        except Exception as e:
            logger.error(f"Error adding relationship: {e}")
            await self.session.rollback()
            raise

    async def find_relationships_by_entity(self, entity_name: str) -> list[dict]:
        """Find relationships involving an entity name."""
        try:
            # 1. Find the entity ID(s)
            stmt = select(EntityORM.id).where(EntityORM.name.ilike(f"%{entity_name}%"))
            result = await self.session.execute(stmt)
            entity_ids = result.scalars().all()

            if not entity_ids:
                return []

            # 2. Find relationships where this entity is subject or object
            # This requires joining with EntityORM twice to get names
            from sqlalchemy.orm import aliased
            SubEntity = aliased(EntityORM)
            ObjEntity = aliased(EntityORM)

            stmt = (
                select(SubEntity.name, RelationshipORM.predicate, ObjEntity.name)
                .join(SubEntity, RelationshipORM.subject_id == SubEntity.id)
                .join(ObjEntity, RelationshipORM.object_id == ObjEntity.id)
                .where(or_(
                    RelationshipORM.subject_id.in_(entity_ids),
                    RelationshipORM.object_id.in_(entity_ids)
                ))
            )
            
            result = await self.session.execute(stmt)
            triples = []
            for sub_name, pred, obj_name in result.all():
                triples.append({
                    "subject": sub_name,
                    "predicate": pred,
                    "object": obj_name
                })
            
            return triples
        except Exception as e:
            logger.error(f"Error finding relationships for '{entity_name}': {e}")
            return []

    async def get_entity_by_name(self, name: str) -> dict | None:
        """Get entity details by name."""
        stmt = select(EntityORM).where(EntityORM.name == name)
        result = await self.session.execute(stmt)
        entity = result.scalars().first()
        if not entity:
            return None
        return {
            "id": entity.id,
            "name": entity.name,
            "type": entity.entity_type,
            "description": entity.description
        }
