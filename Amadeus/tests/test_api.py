import pytest
from unittest.mock import AsyncMock, patch
from fastapi import status

# We use the 'client' and 'auth_headers' fixtures from conftest.py

def test_health_check(client):
    """Test the health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "database" in data

@pytest.mark.asyncio
async def test_create_task(client, auth_headers):
    """Test creating a task."""
    mock_task = {"id": 1, "content": "Test task", "status": "pending"}
    
    with patch("api.task_utils.add_task", new_callable=AsyncMock) as mock_add:
        mock_add.return_value = mock_task
        
        response = client.post(
            "/tasks",
            json={"content": "Test task"},
            headers=auth_headers
        )
        
        assert response.status_code == 201
        data = response.json()
        assert data["content"] == "Test task"
        assert data["id"] == 1
        mock_add.assert_called_once_with("Test task")

@pytest.mark.asyncio
async def test_read_tasks(client, auth_headers):
    """Test listing tasks."""
    mock_tasks = [
        {"id": 1, "content": "Task 1", "status": "pending", "created_at": None},
        {"id": 2, "content": "Task 2", "status": "completed", "created_at": None}
    ]
    
    with patch("api.task_utils.list_tasks", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = mock_tasks
        
        response = client.get("/tasks", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["tasks"]) == 2
        assert data["total"] == 2
        assert data["pending"] == 1
        assert data["completed"] == 1

@pytest.mark.asyncio
async def test_complete_task(client, auth_headers):
    """Test completing a task."""
    with patch("api.task_utils.complete_task", new_callable=AsyncMock) as mock_complete:
        mock_complete.return_value = "Task '1' marked as completed."
        
        response = client.post("/tasks/1/complete", headers=auth_headers)
        
        assert response.status_code == 200
        assert response.json()["message"] == "Task '1' marked as completed."

@pytest.mark.asyncio
async def test_delete_task(client, auth_headers):
    """Test deleting a task."""
    with patch("api.task_utils.delete_task", new_callable=AsyncMock) as mock_delete:
        mock_delete.return_value = "Task '1' deleted successfully."
        
        response = client.delete("/tasks/1", headers=auth_headers)
        
        assert response.status_code == 200
        assert "deleted" in response.json()["message"]

@pytest.mark.asyncio
async def test_create_note(client, auth_headers):
    """Test creating a note."""
    mock_note_create_result = {"status": "success", "id": 10}
    mock_full_note = {
        "status": "success",
        "note": {
            "id": 10,
            "title": "My Note",
            "content": "Note content",
            "tags": ["test"],
            "created_at": None,
            "updated_at": None
        }
    }
    
    with patch("api.note_utils.create_note", new_callable=AsyncMock) as mock_create, \
         patch("api.note_utils.get_note", new_callable=AsyncMock) as mock_get:
        
        mock_create.return_value = mock_note_create_result
        mock_get.return_value = mock_full_note
        
        response = client.post(
            "/notes",
            json={"title": "My Note", "content": "Note content", "tags": ["test"]},
            headers=auth_headers
        )
        
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "My Note"
        assert data["id"] == 10

@pytest.mark.asyncio
async def test_list_notes(client, auth_headers):
    """Test listing notes."""
    mock_notes = [
        {"id": 1, "title": "Note 1", "content": "C1", "tags": []},
        {"id": 2, "title": "Note 2", "content": "C2", "tags": []}
    ]
    
    with patch("api.note_utils.list_notes", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = mock_notes
        
        response = client.get("/notes", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["notes"]) == 2

@pytest.mark.asyncio
async def test_create_reminder(client, auth_headers):
    """Test creating a reminder."""
    mock_create_result = {"status": "success", "id": 5}
    mock_reminders_list = [
        {"id": 5, "title": "Remind me", "time": "2025-01-01T12:00:00Z", "status": "active", "created_at": None}
    ]
    
    with patch("api.reminder_utils.add_reminder", new_callable=AsyncMock) as mock_add, \
         patch("api.reminder_utils.list_reminders", new_callable=AsyncMock) as mock_list:
        
        mock_add.return_value = mock_create_result
        mock_list.return_value = mock_reminders_list
        
        response = client.post(
            "/reminders",
            json={"title": "Remind me", "time_str": "10m"},
            headers=auth_headers
        )
        
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Remind me"
        assert data["status"] == "active"
