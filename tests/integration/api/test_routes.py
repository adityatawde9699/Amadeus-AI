import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(async_client: AsyncClient):
    """The public liveness endpoint reports healthy without auth."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/health/detailed",
        "/api/v1/health/dependencies",
        "/api/v1/system/status",
        "/api/v1/llm/usage",
    ],
)
def test_internal_status_endpoints_require_auth(client, path):
    """Detailed health, dependencies, host resources and LLM usage are private."""
    assert client.get(path).status_code == 401


def test_detailed_health_check(authed_client):
    response = authed_client.get("/api/v1/health/detailed")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "service" in data


def test_system_status(authed_client):
    response = authed_client.get("/api/v1/system/status")
    assert response.status_code == 200
    data = response.json()
    assert "cpu_usage" in data
    assert "memory_usage" in data
    assert "is_healthy" in data


def test_metrics_loopback_only_without_token(client):
    """Without METRICS_TOKEN, metrics answer only loopback peers.

    Starlette's TestClient reports its peer as "testclient" (not loopback).
    """
    assert client.get("/api/v1/metrics").status_code == 403


def test_metrics_token(client, monkeypatch):
    from src.core.config import get_settings

    monkeypatch.setattr(get_settings(), "METRICS_TOKEN", "scrape-me")
    assert client.get("/api/v1/metrics").status_code == 401
    ok = client.get("/api/v1/metrics", headers={"Authorization": "Bearer scrape-me"})
    assert ok.status_code == 200
