"""
Enhanced FastAPI application with Pydantic validation, rate limiting, and security.
"""

from fastapi import FastAPI, HTTPException, Depends, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import List, Optional
import asyncio
import logging
import os

# Local imports
import task_utils
import note_utils
import reminder_utils
from db import init_db_async
from schemas import (
    TaskCreate, TaskResponse, TaskListResponse, TaskUpdate,
    NoteCreate, NoteResponse, NoteListResponse, NoteUpdate,
    ReminderCreate, ReminderResponse, ReminderListResponse,
    ErrorResponse, SuccessResponse, HealthResponse
)
from security import get_api_key, validate_file_path, check_file_permissions, audit_file_operation
from middleware import RateLimitMiddleware, ErrorHandlingMiddleware
from exceptions import NotFoundError, ValidationError, PermissionError
import config

logger = logging.getLogger(__name__)

# ============================================================================
# FASTAPI APP SETUP
# ============================================================================

app = FastAPI(
    title="Amadeus AI Assistant API",
    version="1.0.0",
    description="""
    RESTful API for the Amadeus AI Assistant.
    
    ## Features
    
    * **Tasks Management**: Create, list, complete, and delete tasks
    * **Notes Management**: Create, read, update, and delete notes
    * **Reminders**: Set and manage reminders
    * **Security**: API key authentication and rate limiting
    * **Validation**: Request/response validation with Pydantic models
    
    ## Authentication
    
    Most endpoints require an API key. Include it in the `X-API-Key` header.
    
    ## Rate Limiting
    
    API requests are rate-limited to prevent abuse. Check response headers:
    - `X-RateLimit-Limit`: Maximum requests per window
    - `X-RateLimit-Remaining`: Remaining requests in current window
    - `X-RateLimit-Window`: Time window in seconds
    """,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# Add middleware
app.add_middleware(ErrorHandlingMiddleware)
app.add_middleware(RateLimitMiddleware)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv('CORS_ORIGINS', '*').split(','),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Background task handles
_reminder_task: Optional[asyncio.Task] = None
_reminder_stop_event: Optional[asyncio.Event] = None


# ============================================================================
# LIFECYCLE EVENTS
# ============================================================================

@app.on_event('startup')
async def startup_event():
    """Initialize database and start background tasks."""
    logger.info("Starting Amadeus API...")
    await init_db_async()
    global _reminder_task, _reminder_stop_event
    _reminder_stop_event = asyncio.Event()
    _reminder_task = asyncio.create_task(reminder_utils.check_due_reminders_loop(_reminder_stop_event))
    logger.info("Amadeus API started successfully")


@app.on_event('shutdown')
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("Shutting down Amadeus API...")
    global _reminder_task, _reminder_stop_event
    if _reminder_stop_event:
        _reminder_stop_event.set()
    if _reminder_task:
        await _reminder_task
    logger.info("Amadeus API shut down")


# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.get(
    '/health',
    response_model=HealthResponse,
    tags=['system'],
    summary="Health check endpoint",
    description="Check API health and service status"
)
async def health_check():
    """Health check endpoint."""
    try:
        # Check database connection
        from db import engine
        async with engine.connect() as conn:
            db_status = "connected"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = f"error: {str(e)}"
    
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        database=db_status,
        services={
            "reminder_service": "running" if _reminder_task and not _reminder_task.done() else "stopped"
        }
    )


# ============================================================================
# TASK ENDPOINTS
# ============================================================================

@app.post(
    '/tasks',
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    tags=['tasks'],
    summary="Create a new task",
    description="Create a new task with the provided content",
    dependencies=[Depends(get_api_key)]
)
async def create_task(task: TaskCreate):
    """Create a new task."""
    try:
        result = await task_utils.add_task(task.content)
        return TaskResponse(**result)
    except Exception as e:
        logger.error(f"Error creating task: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create task: {str(e)}"
        )


@app.get(
    '/tasks',
    response_model=TaskListResponse,
    tags=['tasks'],
    summary="List tasks",
    description="Get a list of all tasks, optionally filtered by status",
    dependencies=[Depends(get_api_key)]
)
async def read_tasks(
    status_filter: Optional[str] = Query(None, description="Filter by status (pending/completed)")
):
    """List all tasks."""
    try:
        tasks_data = await task_utils.list_tasks(status_filter)
        
        # Convert to response format
        tasks = [TaskResponse(**task) for task in tasks_data]
        total = len(tasks)
        pending = sum(1 for t in tasks if t.status == "pending")
        completed = sum(1 for t in tasks if t.status == "completed")
        
        return TaskListResponse(
            tasks=tasks,
            total=total,
            pending=pending,
            completed=completed
        )
    except Exception as e:
        logger.error(f"Error listing tasks: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list tasks: {str(e)}"
        )


@app.post(
    '/tasks/{task_id}/complete',
    response_model=SuccessResponse,
    tags=['tasks'],
    summary="Complete a task",
    description="Mark a task as completed by ID or content",
    dependencies=[Depends(get_api_key)]
)
async def complete_task(task_id: str):
    """Mark a task as completed."""
    try:
        result = await task_utils.complete_task(task_id)
        return SuccessResponse(message=result, data={"task_id": task_id})
    except Exception as e:
        logger.error(f"Error completing task: {e}", exc_info=True)
        if "not found" in str(e).lower():
            raise NotFoundError("Task", task_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to complete task: {str(e)}"
        )


@app.delete(
    '/tasks/{task_id}',
    response_model=SuccessResponse,
    tags=['tasks'],
    summary="Delete a task",
    description="Delete a task by ID or content",
    dependencies=[Depends(get_api_key)]
)
async def delete_task(task_id: str):
    """Delete a task."""
    try:
        result = await task_utils.delete_task(task_id)
        return SuccessResponse(message=result, data={"task_id": task_id})
    except Exception as e:
        logger.error(f"Error deleting task: {e}", exc_info=True)
        if "not found" in str(e).lower():
            raise NotFoundError("Task", task_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete task: {str(e)}"
        )


# ============================================================================
# NOTE ENDPOINTS
# ============================================================================

@app.post(
    '/notes',
    response_model=NoteResponse,
    status_code=status.HTTP_201_CREATED,
    tags=['notes'],
    summary="Create a new note",
    description="Create a new note with title, content, and optional tags",
    dependencies=[Depends(get_api_key)]
)
async def create_note(note: NoteCreate):
    """Create a new note."""
    try:
        result = await note_utils.create_note(note.title, note.content, note.tags)
        if result.get("status") == "error":
            raise ValidationError(result.get("message", "Failed to create note"))
        # Fetch the created note to return full details
        note_id = result.get("id")
        if note_id:
            full_note = await note_utils.get_note(note_id)
            if full_note.get("status") == "success":
                return NoteResponse(**full_note["note"])
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve created note"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating note: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create note: {str(e)}"
        )


@app.get(
    '/notes',
    response_model=NoteListResponse,
    tags=['notes'],
    summary="List notes",
    description="Get a list of all notes, optionally filtered by tag",
    dependencies=[Depends(get_api_key)]
)
async def list_notes(tag: Optional[str] = Query(None, description="Filter by tag")):
    """List all notes."""
    try:
        notes_data = await note_utils.list_notes(tag)
        return NoteListResponse(notes=notes_data, total=len(notes_data))
    except Exception as e:
        logger.error(f"Error listing notes: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list notes: {str(e)}"
        )


@app.get(
    '/notes/{note_id}',
    response_model=NoteResponse,
    tags=['notes'],
    summary="Get a note",
    description="Get a specific note by ID",
    dependencies=[Depends(get_api_key)]
)
async def get_note(note_id: int):
    """Get a specific note."""
    try:
        result = await note_utils.get_note(note_id)
        if result.get("status") == "error":
            raise NotFoundError("Note", str(note_id))
        return NoteResponse(**result["note"])
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting note: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get note: {str(e)}"
        )


@app.put(
    '/notes/{note_id}',
    response_model=NoteResponse,
    tags=['notes'],
    summary="Update a note",
    description="Update a note's title, content, or tags",
    dependencies=[Depends(get_api_key)]
)
async def update_note(note_id: int, note_update: NoteUpdate):
    """Update a note."""
    try:
        result = await note_utils.update_note(
            note_id,
            note_update.title,
            note_update.content,
            note_update.tags
        )
        if result.get("status") == "error":
            raise NotFoundError("Note", str(note_id))
        # Fetch updated note
        full_note = await note_utils.get_note(note_id)
        if full_note.get("status") == "success":
            return NoteResponse(**full_note["note"])
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve updated note"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating note: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update note: {str(e)}"
        )


@app.delete(
    '/notes/{note_id}',
    response_model=SuccessResponse,
    tags=['notes'],
    summary="Delete a note",
    description="Delete a note by ID",
    dependencies=[Depends(get_api_key)]
)
async def delete_note(note_id: int):
    """Delete a note."""
    try:
        result = await note_utils.delete_note(note_id)
        if result.get("status") == "error":
            raise NotFoundError("Note", str(note_id))
        return SuccessResponse(message=result.get("message", "Note deleted successfully"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting note: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete note: {str(e)}"
        )


# ============================================================================
# REMINDER ENDPOINTS
# ============================================================================

@app.post(
    '/reminders',
    response_model=ReminderResponse,
    status_code=status.HTTP_201_CREATED,
    tags=['reminders'],
    summary="Create a reminder",
    description="Create a new reminder with title, time string, and optional description",
    dependencies=[Depends(get_api_key)]
)
async def create_reminder(reminder: ReminderCreate):
    """Create a new reminder."""
    try:
        result = await reminder_utils.add_reminder(
            reminder.title,
            reminder.time_str,
            reminder.description
        )
        if result.get("status") == "error":
            raise ValidationError(result.get("message", "Failed to create reminder"))
        # Fetch created reminder
        reminders = await reminder_utils.list_reminders()
        reminder_id = result.get("id")
        created_reminder = next((r for r in reminders if r.get("id") == reminder_id), None)
        if created_reminder:
            return ReminderResponse(**created_reminder)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve created reminder"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating reminder: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create reminder: {str(e)}"
        )


@app.get(
    '/reminders',
    response_model=ReminderListResponse,
    tags=['reminders'],
    summary="List reminders",
    description="Get a list of all active reminders",
    dependencies=[Depends(get_api_key)]
)
async def list_reminders():
    """List all reminders."""
    try:
        reminders_data = await reminder_utils.list_reminders()
        active_count = sum(1 for r in reminders_data if r.get("status") == "active")
        reminders = [ReminderResponse(**r) for r in reminders_data]
        return ReminderListResponse(
            reminders=reminders,
            total=len(reminders),
            active=active_count
        )
    except Exception as e:
        logger.error(f"Error listing reminders: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list reminders: {str(e)}"
        )


@app.delete(
    '/reminders/{reminder_id}',
    response_model=SuccessResponse,
    tags=['reminders'],
    summary="Delete a reminder",
    description="Delete a reminder by ID",
    dependencies=[Depends(get_api_key)]
)
async def delete_reminder(reminder_id: int):
    """Delete a reminder."""
    try:
        result = await reminder_utils.delete_reminder(reminder_id)
        if result.get("status") == "error":
            raise NotFoundError("Reminder", str(reminder_id))
        return SuccessResponse(message=result.get("message", "Reminder deleted successfully"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting reminder: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete reminder: {str(e)}"
        )
