import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(async_client: AsyncClient):
    """Test the basic health check endpoint."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


@pytest.mark.asyncio
async def test_detailed_health_check(async_client: AsyncClient):
    """Test the detailed health check endpoint."""
    response = await async_client.get("/health/detailed")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "Amadeus"


@pytest.mark.asyncio
async def test_system_status(async_client: AsyncClient):
    """Test the system status endpoint."""
    response = await async_client.get("/health/system")
    assert response.status_code == 200
    data = response.json()
    assert "cpu_usage" in data
    assert "memory_usage" in data
    assert "is_healthy" in data


# Note: Chat API and Tasks API require JWT authentication.
# They would be tested here by passing a valid Bearer token in headers.
