"""
Task API routes.

CRUD endpoints for managing tasks/todos.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.core.domain.models import Task, TaskStatus
from src.infra.persistence.database import get_session
from src.infra.persistence.repositories.task_repository import SQLAlchemyTaskRepository


router = APIRouter()


# =============================================================================
# SCHEMAS
# =============================================================================

class TaskCreate(BaseModel):
    """Schema for creating a task."""
    content: str = Field(..., min_length=1, max_length=1000, description="Task content")


class TaskResponse(BaseModel):
    """Schema for task response."""
    id: int
    content: str
    status: str
    created_at: str
    completed_at: str | None = None
    
    @classmethod
    def from_domain(cls, task: Task) -> "TaskResponse":
        return cls(
            id=task.id,
            content=task.content,
            status=task.status.value,
            created_at=task.created_at.isoformat(),
            completed_at=task.completed_at.isoformat() if task.completed_at else None,
        )


class TaskListResponse(BaseModel):
    """Schema for task list response."""
    tasks: list[TaskResponse]
    total: int
    pending: int
    completed: int


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(task: TaskCreate):
    """
    Create a new task.
    
    Args:
        task: The task content to create.
        
    Returns:
        The created task.
    """
    async with get_session() as session:
        repo = SQLAlchemyTaskRepository(session)
        domain_task = Task(content=task.content)
        created = await repo.create(domain_task)
        return TaskResponse.from_domain(created)


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    status_filter: Optional[str] = Query(
        None, 
        description="Filter by status: 'pending' or 'completed'"
    ),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of tasks"),
    offset: int = Query(0, ge=0, description="Number of tasks to skip"),
):
    """
    List all tasks with optional filtering.
    
    Args:
        status_filter: Optional filter by task status.
        limit: Maximum number of tasks to return.
        offset: Number of tasks to skip for pagination.
        
    Returns:
        List of tasks with summary statistics.
    """
    async with get_session() as session:
        repo = SQLAlchemyTaskRepository(session)
        
        if status_filter:
            try:
                status_enum = TaskStatus(status_filter)
                tasks = await repo.get_by_status(status_enum)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid status: {status_filter}. Use 'pending' or 'completed'.",
                )
        else:
            tasks = await repo.get_all(limit=limit, offset=offset)
        
        summary = await repo.get_summary()
        
        return TaskListResponse(
            tasks=[TaskResponse.from_domain(t) for t in tasks],
            total=summary["total"],
            pending=summary["pending"],
            completed=summary["completed"],
        )


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int):
    """
    Get a specific task by ID.
    
    Args:
        task_id: The task's primary key.
        
    Returns:
        The requested task.
        
    Raises:
        HTTPException: If task not found.
    """
    async with get_session() as session:
        repo = SQLAlchemyTaskRepository(session)
        task = await repo.get_by_id(task_id)
        
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task with id {task_id} not found",
            )
        
        return TaskResponse.from_domain(task)


@router.patch("/tasks/{task_id}/complete", response_model=TaskResponse)
async def complete_task(task_id: int):
    """
    Mark a task as completed.
    
    Args:
        task_id: The task's primary key.
        
    Returns:
        The updated task.
        
    Raises:
        HTTPException: If task not found.
    """
    async with get_session() as session:
        repo = SQLAlchemyTaskRepository(session)
        task = await repo.mark_complete(task_id)
        
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task with id {task_id} not found",
            )
        
        return TaskResponse.from_domain(task)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: int):
    """
    Delete a task.
    
    Args:
        task_id: The task's primary key.
        
    Raises:
        HTTPException: If task not found.
    """
    async with get_session() as session:
        repo = SQLAlchemyTaskRepository(session)
        deleted = await repo.delete(task_id)
        
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task with id {task_id} not found",
            )


@router.get("/tasks/summary", response_model=dict)
async def get_tasks_summary():
    """
    Get task statistics summary.
    
    Returns:
        Summary with total, pending, and completed counts.
    """
    async with get_session() as session:
        repo = SQLAlchemyTaskRepository(session)
        return await repo.get_summary()
