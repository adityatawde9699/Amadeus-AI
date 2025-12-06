"""
Pydantic models for API request/response validation.
"""

from pydantic import BaseModel, Field, validator, constr
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# ============================================================================
# COMMON MODELS
# ============================================================================

class StatusEnum(str, Enum):
    """Status enumeration for tasks and reminders."""
    PENDING = "pending"
    COMPLETED = "completed"
    ACTIVE = "active"
    CANCELLED = "cancelled"


class ErrorResponse(BaseModel):
    """Standard error response model."""
    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Detailed error information")
    status_code: int = Field(..., description="HTTP status code")
    timestamp: datetime = Field(default_factory=datetime.now, description="Error timestamp")


class SuccessResponse(BaseModel):
    """Standard success response model."""
    message: str = Field(..., description="Success message")
    status: str = Field(default="success", description="Response status")
    data: Optional[Dict[str, Any]] = Field(None, description="Response data")


# ============================================================================
# TASK MODELS
# ============================================================================

class TaskCreate(BaseModel):
    """Request model for creating a task."""
    content: constr(min_length=1, max_length=1000) = Field(
        ..., 
        description="Task content/description",
        example="Buy groceries"
    )
    
    @validator('content')
    def validate_content(cls, v):
        """Sanitize and validate task content."""
        if not v or not v.strip():
            raise ValueError("Task content cannot be empty")
        # Remove leading/trailing whitespace
        return v.strip()


class TaskResponse(BaseModel):
    """Response model for task operations."""
    id: int = Field(..., description="Task ID")
    content: str = Field(..., description="Task content")
    status: str = Field(..., description="Task status")
    created_at: Optional[str] = Field(None, description="Creation timestamp (ISO format)")
    completed_at: Optional[str] = Field(None, description="Completion timestamp (ISO format)")


class TaskListResponse(BaseModel):
    """Response model for listing tasks."""
    tasks: List[TaskResponse] = Field(..., description="List of tasks")
    total: int = Field(..., description="Total number of tasks")
    pending: int = Field(..., description="Number of pending tasks")
    completed: int = Field(..., description="Number of completed tasks")


class TaskUpdate(BaseModel):
    """Request model for updating a task."""
    content: Optional[constr(min_length=1, max_length=1000)] = Field(
        None, 
        description="Updated task content"
    )
    status: Optional[StatusEnum] = Field(None, description="Updated task status")
    
    @validator('content')
    def validate_content(cls, v):
        """Sanitize task content if provided."""
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Task content cannot be empty")
        return v


# ============================================================================
# NOTE MODELS
# ============================================================================

class NoteCreate(BaseModel):
    """Request model for creating a note."""
    title: constr(min_length=1, max_length=256) = Field(
        ..., 
        description="Note title",
        example="Meeting Notes"
    )
    content: constr(min_length=1, max_length=10000) = Field(
        ..., 
        description="Note content",
        example="Discussion points from today's meeting..."
    )
    tags: Optional[List[constr(max_length=50)]] = Field(
        default_factory=list,
        description="List of tags for the note",
        example=["work", "meeting"]
    )
    
    @validator('title', 'content')
    def validate_text_fields(cls, v):
        """Sanitize text fields."""
        if not v or not v.strip():
            raise ValueError("Field cannot be empty")
        return v.strip()
    
    @validator('tags')
    def validate_tags(cls, v):
        """Validate and sanitize tags."""
        if v is None:
            return []
        # Remove empty tags and limit length
        validated_tags = [tag.strip() for tag in v if tag and tag.strip()]
        # Remove duplicates while preserving order
        seen = set()
        unique_tags = []
        for tag in validated_tags:
            if tag.lower() not in seen:
                seen.add(tag.lower())
                unique_tags.append(tag[:50])  # Enforce max length
        return unique_tags


class NoteResponse(BaseModel):
    """Response model for note operations."""
    id: int = Field(..., description="Note ID")
    title: str = Field(..., description="Note title")
    content: str = Field(..., description="Note content")
    tags: List[str] = Field(default_factory=list, description="Note tags")
    created_at: Optional[str] = Field(None, description="Creation timestamp (ISO format)")
    updated_at: Optional[str] = Field(None, description="Last update timestamp (ISO format)")


class NoteUpdate(BaseModel):
    """Request model for updating a note."""
    title: Optional[constr(min_length=1, max_length=256)] = Field(
        None, 
        description="Updated note title"
    )
    content: Optional[constr(min_length=1, max_length=10000)] = Field(
        None, 
        description="Updated note content"
    )
    tags: Optional[List[constr(max_length=50)]] = Field(
        None, 
        description="Updated list of tags"
    )
    
    @validator('title', 'content')
    def validate_text_fields(cls, v):
        """Sanitize text fields if provided."""
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Field cannot be empty")
        return v
    
    @validator('tags')
    def validate_tags(cls, v):
        """Validate and sanitize tags if provided."""
        if v is None:
            return None
        # Same validation as NoteCreate
        validated_tags = [tag.strip() for tag in v if tag and tag.strip()]
        seen = set()
        unique_tags = []
        for tag in validated_tags:
            if tag.lower() not in seen:
                seen.add(tag.lower())
                unique_tags.append(tag[:50])
        return unique_tags


class NoteListResponse(BaseModel):
    """Response model for listing notes."""
    notes: List[Dict[str, Any]] = Field(..., description="List of notes")
    total: int = Field(..., description="Total number of notes")


# ============================================================================
# REMINDER MODELS
# ============================================================================

class ReminderCreate(BaseModel):
    """Request model for creating a reminder."""
    title: constr(min_length=1, max_length=256) = Field(
        ..., 
        description="Reminder title",
        example="Doctor Appointment"
    )
    time_str: constr(min_length=1, max_length=100) = Field(
        ..., 
        description="Reminder time (human-readable format)",
        example="tomorrow at 3pm"
    )
    description: Optional[constr(max_length=500)] = Field(
        default="",
        description="Optional reminder description",
        example="Annual checkup"
    )
    
    @validator('title')
    def validate_title(cls, v):
        """Sanitize reminder title."""
        if not v or not v.strip():
            raise ValueError("Reminder title cannot be empty")
        return v.strip()
    
    @validator('time_str')
    def validate_time_str(cls, v):
        """Validate time string format."""
        if not v or not v.strip():
            raise ValueError("Time string cannot be empty")
        return v.strip()
    
    @validator('description')
    def validate_description(cls, v):
        """Sanitize description if provided."""
        if v:
            return v.strip()
        return ""


class ReminderResponse(BaseModel):
    """Response model for reminder operations."""
    id: int = Field(..., description="Reminder ID")
    title: str = Field(..., description="Reminder title")
    time: str = Field(..., description="Reminder time (ISO format)")
    description: str = Field(default="", description="Reminder description")
    status: str = Field(..., description="Reminder status")
    created_at: Optional[str] = Field(None, description="Creation timestamp (ISO format)")


class ReminderListResponse(BaseModel):
    """Response model for listing reminders."""
    reminders: List[ReminderResponse] = Field(..., description="List of reminders")
    total: int = Field(..., description="Total number of reminders")
    active: int = Field(..., description="Number of active reminders")


# ============================================================================
# FILE OPERATION MODELS
# ============================================================================

class FileOperationRequest(BaseModel):
    """Request model for file operations."""
    file_path: constr(min_length=1, max_length=1000) = Field(
        ..., 
        description="Path to the file",
        example="/path/to/file.txt"
    )
    
    @validator('file_path')
    def validate_file_path(cls, v):
        """Validate and sanitize file path."""
        if not v or not v.strip():
            raise ValueError("File path cannot be empty")
        # Basic path validation - prevent directory traversal
        v = v.strip()
        # Check for dangerous patterns
        dangerous_patterns = ['../', '..\\', '//', '\\\\']
        for pattern in dangerous_patterns:
            if pattern in v:
                raise ValueError(f"Invalid file path: contains dangerous pattern '{pattern}'")
        return v


class FileOperationResponse(BaseModel):
    """Response model for file operations."""
    success: bool = Field(..., description="Operation success status")
    message: str = Field(..., description="Operation result message")
    file_path: Optional[str] = Field(None, description="File path")


# ============================================================================
# HEALTH CHECK MODELS
# ============================================================================

class HealthResponse(BaseModel):
    """Response model for health check endpoint."""
    status: str = Field(..., description="Service status")
    version: str = Field(..., description="API version")
    timestamp: datetime = Field(default_factory=datetime.now, description="Check timestamp")
    database: str = Field(..., description="Database connection status")
    services: Dict[str, str] = Field(default_factory=dict, description="Service statuses")

