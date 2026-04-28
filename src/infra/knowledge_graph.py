"""
Knowledge Graph (KG) Service for Amadeus AI.

Manages episodic memory as SPO triples: (Subject) —[Predicate]→ (Object).
Stored in SQLite using EntityORM and RelationshipORM.
"""

from __future__ import annotations

import logging
from typing import Any
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from src.infra.persistence.orm_models import EntityORM, RelationshipORM
from src.infra.persistence.database import get_session

logger = logging.getLogger(__name__)

class KnowledgeGraphService:
    """
    Manages episodic memory using a Knowledge Graph structure.
    
    Provides storage and retrieval of (Subject, Predicate, Object) triples
    to support structured factual recall within the AI's tiered memory architecture.
    """

    def __init__(self, session_factory: Any = None) -> None:
        self._session_factory = session_factory or get_session

    async def add_triple(
        self, 
        subject_name: str, 
        predicate: str, 
        object_name: str, 
        subject_type: str | None = None, 
        object_type: str | None = None
    ) -> bool:
        """
        Add a triple (S, P, O) to the Knowledge Graph.
        """
        async with self._session_factory() as session:
            try:
                # 1. Get or create entities
                sub_id = await self._get_or_create_entity(session, subject_name, subject_type)
                obj_id = await self._get_or_create_entity(session, object_name, object_type)

                # 2. Add relationship
                # Check if it already exists to avoid duplicates
                stmt = select(RelationshipORM).where(
                    RelationshipORM.subject_id == sub_id,
                    RelationshipORM.predicate == predicate,
                    RelationshipORM.object_id == obj_id
                )
                existing = (await session.execute(stmt)).scalars().first()
                
                if not existing:
                    rel = RelationshipORM(
                        subject_id=sub_id,
                        predicate=predicate,
                        object_id=obj_id
                    )
                    session.add(rel)
                    await session.commit()
                    logger.debug(
                        "KG triple added: (%s) -[%s]-> (%s)",
                        subject_name,
                        predicate,
                        object_name,
                    )
                
                return True
            except Exception as e:
                logger.error("Failed to add KG triple: %s", e)
                await session.rollback()
                return False

    async def _get_or_create_entity(self, session: AsyncSession, name: str, entity_type: str | None = None) -> int:
        stmt = select(EntityORM).where(EntityORM.name == name)
        result = await session.execute(stmt)
        entity = result.scalars().first()

        if not entity:
            entity = EntityORM(name=name, entity_type=entity_type)
            session.add(entity)
            await session.flush()  # Get ID without committing
        
        return entity.id

    async def retrieve_triples(self, query: str, limit: int = 5) -> list[str]:
        """
        Retrieve triples relevant to the query based on entity name matching.
        """
        # Extract keywords from query (very basic heuristic)
        words = [w.strip("?,.!") for w in query.split() if len(w) > 3]
        if not words:
            return []

        async with self._session_factory() as session:
            try:
                # 1. Find entities mentioned in query (simple ilike match)
                # This could be improved with an LLM-based entity extractor
                entity_filters = [EntityORM.name.ilike(f"%{word}%") for word in words]
                stmt = select(EntityORM).where(or_(*entity_filters))
                result = await session.execute(stmt)
                entities = result.scalars().all()
                entity_ids = [e.id for e in entities]

                if not entity_ids:
                    return []

                # 2. Find relationships involving these entities
                rel_stmt = select(RelationshipORM).where(
                    or_(
                        RelationshipORM.subject_id.in_(entity_ids),
                        RelationshipORM.object_id.in_(entity_ids)
                    )
                ).limit(limit)
                
                rel_result = await session.execute(rel_stmt)
                relationships = rel_result.scalars().all()

                # 3. Resolve IDs back to names and format strings
                triples = []
                for rel in relationships:
                    # Get subject name
                    sub_stmt = select(EntityORM).where(EntityORM.id == rel.subject_id)
                    sub = (await session.execute(sub_stmt)).scalars().first()
                    # Get object name
                    obj_stmt = select(EntityORM).where(EntityORM.id == rel.object_id)
                    obj = (await session.execute(obj_stmt)).scalars().first()
                    
                    if sub and obj:
                        triples.append(f"- ({sub.name}) —[{rel.predicate}]→ ({obj.name})")

                return triples
            except Exception as e:
                logger.error("Failed to retrieve KG triples: %s", e)
                return []
