"""
Pytest configuration and shared fixtures.

This module provides fixtures for testing the Amadeus AI application.
"""

import asyncio
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.config import Settings, get_settings
from src.infra.persistence.database import Base, get_session, get_engine


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
        VOICE_ENABLED=False,
        SKIP_CONFIG_VALIDATION=True,
    )


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Provide test settings for the session."""
    return get_test_settings()


# =============================================================================
# DATABASE FIXTURES
# =============================================================================

@pytest_asyncio.fixture(scope="function")
async def test_db():
    """
    Create a fresh test database for each test function.
    
    Uses an in-memory SQLite database for speed.
    """
    # Create in-memory database
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
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
    
    # Yield the factory
    yield session_factory
    
    # Cleanup
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

@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
