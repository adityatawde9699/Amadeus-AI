"""
Pytest configuration and shared fixtures.

This module provides fixtures for testing the Amadeus AI application.
"""

from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.core.config import Settings
from src.infra.persistence.database import Base


# =============================================================================
# TEST SETTINGS
# =============================================================================


def get_test_settings() -> Settings:
    """Get settings configured for testing."""
    return Settings(
        ENV="development",
        DEBUG=True,
        DATABASE_URL="sqlite:///./test_amadeus.db",
        GEMINI_API_KEY="test_key",
        SECRET_KEY="test-secret-key-32-chars-minimum-xx",  # Required for JWT
        SKIP_CONFIG_VALIDATION=True,
    )


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Provide test settings for the session."""
    return get_test_settings()


# =============================================================================
# DATABASE FIXTURES
# =============================================================================


@pytest.fixture(scope="session")
def postgres_container():
    """Start a PostgreSQL container for the test session."""
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:15-alpine") as postgres:
        yield postgres


@pytest_asyncio.fixture(scope="function")
async def test_db(postgres_container):
    """
    Create a fresh test database for each test function using testcontainers.
    """
    db_url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2", "postgresql+asyncpg"
    )

    # Create engine for test DB
    engine = create_async_engine(
        db_url,
        echo=False,
        poolclass=StaticPool,
    )

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create session factory
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    yield session_factory

    # Cleanup tables after test
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_db) -> AsyncGenerator[AsyncSession, None]:
    """Provide a database session for a single test."""
    async with test_db() as session:
        yield session
        await session.rollback()


# =============================================================================
# API CLIENT FIXTURES
# =============================================================================


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    """Provide a test client for synchronous API tests."""
    from src.api.server import app

    with TestClient(app) as c:
        yield c


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an async test client for async API tests."""
    from src.api.server import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# =============================================================================
# EVENT LOOP CONFIGURATION
# =============================================================================
# NOTE: event_loop fixture removed — deprecated in pytest-asyncio >= 0.23.
# asyncio_default_fixture_loop_scope = "function" is set in pyproject.toml.
# Each test function gets its own event loop automatically.
