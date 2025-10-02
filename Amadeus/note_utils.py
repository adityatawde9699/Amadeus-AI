from typing import Optional, List, Dict
from db import get_async_session, init_db_async
import models
from datetime import datetime
from sqlalchemy import select, update, delete


# Note: call await init_db_async() at app startup to ensure tables exist


async def create_note(title: str, content: str, tags: Optional[List[str]] = None) -> Dict:
    if not title or not content:
        return {"status": "error", "message": "Title and content are required"}
    async with get_async_session() as db:
        note = models.Note(title=title, content=content, tags=','.join(tags or []))
        db.add(note)
        await db.commit()
        await db.refresh(note)
        return {"status": "success", "message": f"Note '{title}' created successfully", "id": note.id}


async def list_notes(tag: Optional[str] = None) -> List[Dict]:
    async with get_async_session() as db:
        stmt = select(models.Note)
        if tag:
            stmt = stmt.where(models.Note.tags.ilike(f"%{tag}%"))
        stmt = stmt.order_by(models.Note.created_at.desc())
        res = await db.execute(stmt)
        notes = res.scalars().all()
        result = []
        for n in notes:
            tags_val = getattr(n, 'tags', None)
            created_at = getattr(n, 'created_at', None)
            result.append({
                "id": getattr(n, 'id', None),
                "title": getattr(n, 'title', None),
                "tags": tags_val.split(',') if tags_val else [],
                "created_at": created_at.isoformat() if created_at is not None else None,
            })
        return result


async def get_note(note_id: int) -> Dict:
    async with get_async_session() as db:
        stmt = select(models.Note).where(models.Note.id == note_id)
        res = await db.execute(stmt)
        note = res.scalars().first()
        if not note:
            return {"status": "error", "message": f"Note with ID {note_id} not found"}
        tags = note.tags.split(',') if note.tags is not None else []
        created_at = note.created_at.isoformat() if note.created_at is not None else None
        return {"status": "success", "note": {"id": note.id, "title": note.title, "content": note.content, "tags": tags, "created_at": created_at}}


async def update_note(note_id: int, title: Optional[str] = None, content: Optional[str] = None, tags: Optional[List[str]] = None) -> Dict:
    async with get_async_session() as db:
        stmt = select(models.Note).where(models.Note.id == note_id)
        res = await db.execute(stmt)
        note = res.scalars().first()
        if not note:
            return {"status": "error", "message": f"Note with ID {note_id} not found"}
        vals = {}
        if title:
            vals['title'] = title
        if tags is not None:
            vals['tags'] = ','.join(tags)
        if content is not None:
            vals['content'] = content
        if vals:
            vals['updated_at'] = datetime.utcnow()
            await db.execute(update(models.Note).where(models.Note.id == note_id).values(**vals))
            await db.commit()
        return {"status": "success", "message": "Note updated successfully"}


async def delete_note(note_id: int) -> Dict:
    async with get_async_session() as db:
        stmt = select(models.Note).where(models.Note.id == note_id)
        res = await db.execute(stmt)
        note = res.scalars().first()
        if not note:
            return {"status": "error", "message": f"Note with ID {note_id} not found"}
        await db.execute(delete(models.Note).where(models.Note.id == note_id))
        await db.commit()
        return {"status": "success", "message": "Note deleted successfully"}


async def get_notes_summary() -> str:
    async with get_async_session() as db:
        res = await db.execute(select(models.Note))
        notes = res.scalars().all()
        total_notes = len(notes)
        if total_notes == 0:
            return "You have no notes."
        tag_count = {}
        for n in notes:
            tags_val = getattr(n, 'tags', None)
            for tag in (tags_val.split(',') if tags_val else []):
                if not tag:
                    continue
                tag_count[tag] = tag_count.get(tag, 0) + 1
        sorted_tags = sorted(tag_count.items(), key=lambda x: x[1], reverse=True)
        top_tags = sorted_tags[:5]
        top_tags_str = ", ".join([f"{tag} ({count})" for tag, count in top_tags])
        recent_notes = [n.title for n in sorted(notes, key=lambda x: x.created_at, reverse=True)[:3]]
        recent_notes_str = ", ".join([f'"{t}"' for t in recent_notes])
        summary = f"You have {total_notes} notes."
        if top_tags:
            summary += f" Your most used tags are: {top_tags_str}."
        if recent_notes:
            summary += f" Your most recent notes are: {recent_notes_str}."
        return summary