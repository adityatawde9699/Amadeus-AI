import json
import os
import datetime
from pathlib import Path
from typing import Dict, List, Optional

# File path for persistent storage
NOTES_DIR = Path("notes")
NOTES_INDEX_FILE = NOTES_DIR / "index.json"

def init_notes_storage():
    """Initialize notes storage directory and index file."""
    if not NOTES_DIR.exists():
        NOTES_DIR.mkdir(parents=True, exist_ok=True)
    
    if not NOTES_INDEX_FILE.exists():
        with open(NOTES_INDEX_FILE, "w") as f:
            json.dump({"notes": []}, f, indent=2)

# Initialize storage on import
init_notes_storage()

def load_notes_index() -> Dict:
    """Load the notes index from JSON file."""
    try:
        with open(NOTES_INDEX_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading notes index: {e}")
        return {"notes": []}

def save_notes_index(index: Dict) -> bool:
    """Save the notes index to JSON file."""
    try:
        with open(NOTES_INDEX_FILE, "w") as f:
            json.dump(index, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving notes index: {e}")
        return False

def create_note(title: str, content: str, tags: Optional[List[str]] = None) -> Dict:
    """Create a new note."""
    if not title or not content:
        return {"status": "error", "message": "Title and content are required"}
    
    try:
        # Generate a unique filename
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        note_id = f"{timestamp}_{title.lower().replace(' ', '_')[:30]}"
        filename = f"{note_id}.txt"
        file_path = NOTES_DIR / filename
        
        # Write note content to file
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        
        # Update index
        index = load_notes_index()
        index["notes"].append({
            "id": note_id,
            "title": title,
            "filename": filename,
            "created_at": datetime.datetime.now().isoformat(),
            "updated_at": datetime.datetime.now().isoformat(),
            "tags": tags or []
        })
        save_notes_index(index)
        
        return {"status": "success", "message": f"Note '{title}' created successfully", "id": note_id}
    except Exception as e:
        return {"status": "error", "message": f"Error creating note: {str(e)}"}

def list_notes(tag: Optional[str] = None) -> List[Dict]:
    """List all notes, optionally filtered by tag."""
    try:
        index = load_notes_index()
        notes = index.get("notes", [])
        
        if tag:
            notes = [note for note in notes if tag.lower() in [t.lower() for t in note.get("tags", [])]]
            
        # Sort by creation date, newest first
        notes.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        
        return notes
    except Exception as e:
        print(f"Error listing notes: {e}")
        return []

def get_note(note_id: str) -> Dict:
    """Get a note by ID with its content."""
    try:
        index = load_notes_index()
        notes = index.get("notes", [])
        
        # Find the note in the index
        matching_notes = [note for note in notes if note.get("id") == note_id]
        if not matching_notes:
            return {"status": "error", "message": f"Note with ID {note_id} not found"}
        
        note = matching_notes[0]
        file_path = NOTES_DIR / note.get("filename")
        
        # Read content from file
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            return {
                "status": "success",
                "note": {
                    **note,
                    "content": content
                }
            }
        else:
            return {"status": "error", "message": f"Note file not found: {note.get('filename')}"}
    except Exception as e:
        return {"status": "error", "message": f"Error getting note: {str(e)}"}

def update_note(note_id: str, title: Optional[str] = None, content: Optional[str] = None, 
                tags: Optional[List[str]] = None) -> Dict:
    """Update an existing note."""
    try:
        index = load_notes_index()
        notes = index.get("notes", [])
        
        # Find the note in the index
        for i, note in enumerate(notes):
            if note.get("id") == note_id:
                # Update note metadata
                if title:
                    notes[i]["title"] = title
                if tags is not None:
                    notes[i]["tags"] = tags
                notes[i]["updated_at"] = datetime.datetime.now().isoformat()
                
                # Update content if provided
                if content is not None:
                    file_path = NOTES_DIR / note.get("filename")
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(content)
                
                save_notes_index(index)
                return {"status": "success", "message": f"Note updated successfully"}
                
        return {"status": "error", "message": f"Note with ID {note_id} not found"}
    except Exception as e:
        return {"status": "error", "message": f"Error updating note: {str(e)}"}

def request_delete_note(note_id: str) -> Dict:
    """Request to delete a note (first step of two-step deletion)."""
    try:
        index = load_notes_index()
        notes = index.get("notes", [])
        
        # Find the note in the index
        matching_notes = [note for note in notes if note.get("id") == note_id]
        if not matching_notes:
            return {"status": "error", "message": f"Note with ID {note_id} not found"}
        
        note = matching_notes[0]
        return {
            "status": "confirm_needed",
            "message": f"Are you sure you want to delete the note '{note.get('title')}'? This cannot be undone."
        }
    except Exception as e:
        return {"status": "error", "message": f"Error preparing note deletion: {str(e)}"}

def confirm_delete_note(note_id: str) -> Dict:
    """Confirm and execute note deletion (second step of two-step deletion)."""
    try:
        index = load_notes_index()
        notes = index.get("notes", [])
        
        # Find the note in the index
        for i, note in enumerate(notes):
            if note.get("id") == note_id:
                # Delete the file
                file_path = NOTES_DIR / note.get("filename")
                if file_path.exists():
                    os.remove(file_path)
                
                # Remove from index
                del notes[i]
                save_notes_index(index)
                
                return {"status": "success", "message": f"Note deleted successfully"}
        
        return {"status": "error", "message": f"Note with ID {note_id} not found"}
    except Exception as e:
        return {"status": "error", "message": f"Error deleting note: {str(e)}"}

def get_notes_summary() -> str:
    """Get a summary of notes."""
    try:
        notes = list_notes()
        total_notes = len(notes)
        
        if total_notes == 0:
            return "You have no notes."
            
        # Get tags
        all_tags = []
        for note in notes:
            all_tags.extend(note.get("tags", []))
        
        # Count tag occurrences
        tag_count = {}
        for tag in all_tags:
            tag_count[tag] = tag_count.get(tag, 0) + 1
        
        # Sort tags by frequency
        sorted_tags = sorted(tag_count.items(), key=lambda x: x[1], reverse=True)
        top_tags = sorted_tags[:5] if len(sorted_tags) > 5 else sorted_tags
        
        top_tags_str = ", ".join([f"{tag} ({count})" for tag, count in top_tags])
        recent_notes = [note.get("title") for note in notes[:3]]
        recent_notes_str = ", ".join([f'"{title}"' for title in recent_notes])
        
        summary = f"You have {total_notes} notes."
        if top_tags:
            summary += f" Your most used tags are: {top_tags_str}."
        if recent_notes:
            summary += f" Your most recent notes are: {recent_notes_str}."
            
        return summary
    except Exception as e:
        return f"Error generating notes summary: {e}"