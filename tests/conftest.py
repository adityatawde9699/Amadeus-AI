"""
Pytest configuration and shared fixtures.

This module provides fixtures for testing the Amadeus AI application.
"""

import os
import tempfile
from collections.abc import AsyncGenerator, Generator


# =============================================================================
# TEST ENVIRONMENT ISOLATION — must run before ANY ``src`` import
# =============================================================================
# Settings come from env vars first, then ``.env``. Without these overrides the
# API fixtures start the real app with the developer's ``.env``: Alembic
# migrations and test rows hit the configured (possibly cloud) database, the real
# Telegram bot starts polling, and Redis/Sentry/LLM providers are contacted.
# Env vars beat ``.env`` in pydantic-settings, so pin everything external here.
# To run against a real Postgres (CI), set AMADEUS_TEST_DATABASE_URL.
_TEST_DIR = tempfile.mkdtemp(prefix="amadeus-tests-")
_TEST_ENV = {
    "ENV": "development",
    "SKIP_CONFIG_VALIDATION": "true",
    "DATABASE_URL": os.environ.get(
        "AMADEUS_TEST_DATABASE_URL", f"sqlite:///{_TEST_DIR}/amadeus_test.db"
    ),
    "SECRET_KEY": "test-secret-key-32-chars-minimum-xx",
    "REDIS_URL": "redis://127.0.0.1:1/0",  # unreachable → in-memory fallbacks
    "SENTRY_DSN": "",
    "TELEGRAM_BOT_TOKEN": "",
    "TELEGRAM_WEBHOOK_URL": "",
    "MASTER_TELEGRAM_CHAT_ID": "",
    "WHATSAPP_ACCESS_TOKEN": "",
    "EMAIL_ADDRESS": "",
    "EMAIL_APP_PASSWORD": "",
    "GEMINI_API_KEY": "",
    "GROQ_API_KEY": "",
    "TAVILY_API_KEY": "",
    "LOCAL_ONLY_MODE": "true",
    "MODEL_DOWNLOAD_ENABLED": "false",
    "ENABLE_MCP": "false",
    "ENABLE_PROACTIVE_LOOP": "false",
    "ENABLE_AUTONOMOUS_LOOP": "false",
    "DATA_DIR": _TEST_DIR,
}
os.environ.update(_TEST_ENV)

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
    from src.transports.fastapi_transport import app

    with TestClient(app) as c:
        yield c


def _fake_user(role: str = "admin", user_id: int = 1):
    from types import SimpleNamespace

    from src.infra.persistence.orm_models import UserRoleDB

    return SimpleNamespace(id=user_id, role=UserRoleDB(role), is_active=True)


@pytest.fixture
def authed_client(client: TestClient) -> Generator[TestClient, None, None]:
    """``client`` with RBAC satisfied by a fake ADMIN user.

    Admin keeps task routes unscoped (``owner_id`` NULL), so the tests don't
    need a real ``users`` row for the tasks.owner_id foreign key. Per-user
    scoping is covered against a real DB in tests/unit/test_task_tenancy.py.
    """
    from src.api.middleware.rbac import RequireUser
    from src.transports.fastapi_transport import app

    app.dependency_overrides[RequireUser] = _fake_user
    try:
        yield client
    finally:
        app.dependency_overrides.pop(RequireUser, None)


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an async test client for async API tests."""
    from src.transports.fastapi_transport import app

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
