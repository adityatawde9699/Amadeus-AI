from typing import Optional, List, Dict
from db import SessionLocal, init_db
import models
from sqlalchemy.orm import Session
from datetime import datetime


# Ensure DB tables exist
init_db()


def _get_session() -> Session:
    return SessionLocal()


def create_note(title: str, content: str, tags: Optional[List[str]] = None) -> Dict:
    if not title or not content:
        return {"status": "error", "message": "Title and content are required"}
    with _get_session() as db:
        note = models.Note(title=title, content=content, tags=','.join(tags or []))
        db.add(note)
        db.commit()
        db.refresh(note)
        return {"status": "success", "message": f"Note '{title}' created successfully", "id": note.id}


def list_notes(tag: Optional[str] = None) -> List[Dict]:
    with _get_session() as db:
        query = db.query(models.Note)
        if tag:
            query = query.filter(models.Note.tags.ilike(f"%{tag}%"))
        notes = query.order_by(models.Note.created_at.desc()).all()
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


def get_note(note_id: int) -> Dict:
    with _get_session() as db:
        note = db.query(models.Note).get(note_id)
        if not note:
            return {"status": "error", "message": f"Note with ID {note_id} not found"}
        return {"status": "success", "note": {"id": note.id, "title": note.title, "content": note.content, "tags": note.tags.split(',') if note.tags else [], "created_at": note.created_at.isoformat() if note.created_at else None}}


def update_note(note_id: int, title: Optional[str] = None, content: Optional[str] = None, tags: Optional[List[str]] = None) -> Dict:
    with _get_session() as db:
        note = db.query(models.Note).get(note_id)
        if not note:
            return {"status": "error", "message": f"Note with ID {note_id} not found"}
        if title:
            note.title = title
        if tags is not None:
            note.tags = ','.join(tags)
        if content is not None:
            note.content = content
        note.updated_at = datetime.utcnow()
        db.add(note)
        db.commit()
        return {"status": "success", "message": "Note updated successfully"}


def delete_note(note_id: int) -> Dict:
    with _get_session() as db:
        note = db.query(models.Note).get(note_id)
        if not note:
            return {"status": "error", "message": f"Note with ID {note_id} not found"}
        db.delete(note)
        db.commit()
        return {"status": "success", "message": "Note deleted successfully"}


def get_notes_summary() -> str:
    with _get_session() as db:
        notes = db.query(models.Note).all()
        total_notes = len(notes)
        if total_notes == 0:
            return "You have no notes."
        # Aggregate tags
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