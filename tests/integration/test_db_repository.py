import pytest
from src.infra.persistence.database import get_engine
from src.core.domain.models import Task, TaskStatus
from src.infra.persistence.repositories.task_repository import SQLAlchemyTaskRepository
from src.infra.persistence.orm_models import TaskORM

@pytest.mark.asyncio
async def test_task_repository_create_and_get(test_db):
    """Test creating and retrieving a task from the Postgres test DB."""
    async with test_db() as session:
        repo = SQLAlchemyTaskRepository(session)
        
        # Create a task
        new_task = Task(content="Test PostgreSQL Integration")
        created_task = await repo.create(new_task)
        
        assert created_task.id is not None
        assert created_task.content == "Test PostgreSQL Integration"
        assert created_task.status == TaskStatus.PENDING
        
        # Get the task
        retrieved_task = await repo.get_by_id(created_task.id)
        assert retrieved_task is not None
        assert retrieved_task.id == created_task.id
        assert retrieved_task.content == created_task.content

@pytest.mark.asyncio
async def test_task_repository_get_all(test_db):
    """Test retrieving multiple tasks."""
    async with test_db() as session:
        repo = SQLAlchemyTaskRepository(session)
        
        # Create tasks
        await repo.create(Task(content="Task 1"))
        await repo.create(Task(content="Task 2"))
        
        # Get all tasks
        tasks = await repo.get_all()
        assert len(tasks) >= 2
        assert tasks[0].content == "Task 1"
        assert tasks[1].content == "Task 2"

@pytest.mark.asyncio
async def test_task_repository_mark_complete(test_db):
    """Test marking a task as complete."""
    async with test_db() as session:
        repo = SQLAlchemyTaskRepository(session)
        
        # Create a task
        task = await repo.create(Task(content="To Be Completed"))
        assert task.status == TaskStatus.PENDING
        assert task.completed_at is None
        
        # Mark complete
        completed_task = await repo.mark_complete(task.id)
        assert completed_task is not None
        assert completed_task.status == TaskStatus.COMPLETED
        assert completed_task.completed_at is not None
        
        # Verify in DB
        db_task = await repo.get_by_id(task.id)
        assert db_task.status == TaskStatus.COMPLETED

@pytest.mark.asyncio
async def test_task_repository_delete(test_db):
    """Test deleting a task."""
    async with test_db() as session:
        repo = SQLAlchemyTaskRepository(session)
        
        # Create a task
        task = await repo.create(Task(content="To Be Deleted"))
        
        # Delete task
        deleted = await repo.delete(task.id)
        assert deleted is True
        
        # Verify deletion
        db_task = await repo.get_by_id(task.id)
        assert db_task is None
