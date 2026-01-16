"""
SQL Conversation Repository for persistent conversation history.

Implements IConversationRepository using SQLAlchemy async sessions.
"""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import delete, desc, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.interfaces.repositories import IConversationRepository
from src.infra.persistence.orm_models import MessageORM


logger = logging.getLogger(__name__)


class SQLConversationRepository(IConversationRepository):
    """SQLAlchemy implementation of conversation repository."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_used: str | None = None,
    ) -> None:
        """Add a message to the conversation history."""
        message = MessageORM(
            session_id=session_id,
            role=role,
            content=content,
            tool_used=tool_used,
        )
        self.session.add(message)
        await self.session.commit()
        logger.debug(f"Saved message: session={session_id[:8]}..., role={role}")
    
    async def get_recent_context(
        self,
        session_id: str,
        limit: int = 10,
    ) -> list[dict]:
        """Get recent messages for context (oldest to newest)."""
        stmt = (
            select(MessageORM)
            .where(MessageORM.session_id == session_id)
            .order_by(desc(MessageORM.timestamp))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        messages = result.scalars().all()
        
        # Convert to dicts and reverse to get chronological order
        return [
            {
                "role": msg.role,
                "content": msg.content,
                "tool_used": msg.tool_used,
                "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
            }
            for msg in reversed(messages)
        ]
    
    async def get_session_history(self, session_id: str) -> list[dict]:
        """Get all messages for a session."""
        stmt = (
            select(MessageORM)
            .where(MessageORM.session_id == session_id)
            .order_by(MessageORM.timestamp.asc())
        )
        result = await self.session.execute(stmt)
        messages = result.scalars().all()
        
        return [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "tool_used": msg.tool_used,
                "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
            }
            for msg in messages
        ]
    
    async def clear_session(self, session_id: str) -> int:
        """Clear all messages for a session."""
        stmt = delete(MessageORM).where(MessageORM.session_id == session_id)
        result = await self.session.execute(stmt)
        await self.session.commit()
        count = result.rowcount
        logger.info(f"Cleared {count} messages from session {session_id[:8]}...")
        return count
    
    async def list_sessions(self, limit: int = 20) -> list[str]:
        """List recent session IDs."""
        # Get distinct session_ids with their most recent timestamp
        stmt = (
            select(
                MessageORM.session_id,
                func.max(MessageORM.timestamp).label("last_activity")
            )
            .group_by(MessageORM.session_id)
            .order_by(desc("last_activity"))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        rows = result.all()
        return [row.session_id for row in rows]
