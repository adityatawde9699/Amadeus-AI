"""
Integration tests for API health endpoints.

Tests the API server startup and health check endpoints.
"""

import pytest
from fastapi import status


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_root_endpoint(self, client):
        """Test the root endpoint returns API info."""
        response = client.get("/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert "message" in data
        assert "Amadeus" in data["message"]
        assert "version" in data

    def test_health_endpoint(self, client):
        """Test the basic health check endpoint."""
        response = client.get("/health")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert data["status"] == "healthy"
        assert "service" in data
        assert "version" in data
        assert "environment" in data

    def test_detailed_health_endpoint(self, authed_client):
        """Test the detailed health check endpoint."""
        response = authed_client.get("/api/v1/health/detailed")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert data["status"] == "healthy"
        assert "database" in data

    def test_system_status_endpoint(self, authed_client):
        """Test the system status endpoint."""
        response = authed_client.get("/api/v1/system/status")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Check required fields
        assert "cpu_usage" in data
        assert "memory_usage" in data
        assert "disk_usage" in data
        assert "is_healthy" in data
        assert "alerts" in data

        # Check value ranges
        assert 0 <= data["cpu_usage"] <= 100
        assert 0 <= data["memory_usage"] <= 100
        assert 0 <= data["disk_usage"] <= 100


class TestTaskEndpoints:
    """Integration tests for task API endpoints (authenticated)."""

    def test_tasks_require_auth(self, client):
        assert client.get("/api/v1/tasks").status_code == 401

    def test_task_summary_route_not_shadowed(self, authed_client):
        """/tasks/summary must not be captured by /tasks/{task_id} (was 422)."""
        response = authed_client.get("/api/v1/tasks/summary")
        assert response.status_code == status.HTTP_200_OK
        assert set(response.json()) == {"total", "pending", "completed"}

    def test_create_task(self, authed_client):
        """Test creating a new task."""
        response = authed_client.post("/api/v1/tasks", json={"content": "Test task from integration test"})

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()

        assert data["content"] == "Test task from integration test"
        assert data["status"] == "pending"
        assert "id" in data
        assert "created_at" in data

    def test_list_tasks(self, authed_client):
        """Test listing tasks."""
        # Create a task first
        authed_client.post("/api/v1/tasks", json={"content": "Task for listing"})

        response = authed_client.get("/api/v1/tasks")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert "tasks" in data
        assert "total" in data
        assert "pending" in data
        assert "completed" in data
        assert isinstance(data["tasks"], list)

    def test_create_task_validation(self, authed_client):
        """Test task creation validation."""
        # Empty content should fail
        response = authed_client.post("/api/v1/tasks", json={"content": ""})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_get_nonexistent_task(self, authed_client):
        """Test getting a task that doesn't exist."""
        response = authed_client.get("/api/v1/tasks/99999")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_filter_tasks_by_status(self, authed_client):
        """Test filtering tasks by status."""
        # Get only pending tasks
        response = authed_client.get("/api/v1/tasks?status_filter=pending")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        for task in data["tasks"]:
            assert task["status"] == "pending"


@pytest.mark.asyncio
class TestAsyncHealthEndpoints:
    """Async tests for health endpoints."""

    async def test_health_async(self, async_client):
        """Test health endpoint with async client."""
        response = await async_client.get("/health")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "healthy"
