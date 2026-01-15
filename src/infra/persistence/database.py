"""
Database configuration and session management.

This module provides async database engine, session factory, and
context manager for database operations. It supports both SQLite
(development) and PostgreSQL (production).

Usage:
    from src.infra.persistence.database import get_session, init_db
    
    async with get_session() as session:
        # Use session for database operations
        ...
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool, StaticPool

from src.core.config import get_settings


logger = logging.getLogger(__name__)

# Base class for all ORM models
Base = declarative_base()

# Global engine and session factory (initialized lazily)
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_db_initialized: bool = False


def get_engine() -> AsyncEngine:
    """
    Get or create the async database engine.
    
    Returns:
        The async SQLAlchemy engine.
    """
    global _engine
    
    if _engine is not None:
        return _engine
    
    settings = get_settings()
    async_db_url = settings.get_async_database_url()
    
    # Different pool configuration for SQLite vs other databases
    if settings.database_is_sqlite:
        # Determine if in-memory or file-based SQLite
        is_memory = ":memory:" in async_db_url.lower()
        pool_class = StaticPool if is_memory else NullPool
        
        _engine = create_async_engine(
            async_db_url,
            echo=settings.DB_ECHO,
            future=True,
            poolclass=pool_class,
            pool_pre_ping=True,
            connect_args={
                "check_same_thread": False,
                "timeout": settings.DB_POOL_TIMEOUT,
            },
        )
    else:
        # Connection pool for PostgreSQL, MySQL, etc.
        _engine = create_async_engine(
            async_db_url,
            echo=settings.DB_ECHO,
            future=True,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_recycle=settings.DB_POOL_RECYCLE,
            pool_pre_ping=True,
        )
    
    logger.info(f"Database engine created: {async_db_url.split('@')[-1] if '@' in async_db_url else async_db_url}")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """
    Get or create the async session factory.
    
    Returns:
        The async session factory.
    """
    global _session_factory
    
    if _session_factory is not None:
        return _session_factory
    
    engine = get_engine()
    
    _session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,  # Don't expire objects after commit
        autoflush=True,
        autocommit=False,
    )
    
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager for database sessions.
    
    Handles commit on success and rollback on exception.
    
    Usage:
        async with get_session() as session:
            result = await session.execute(query)
            
    Yields:
        An async database session.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """
    Initialize the database by creating all tables.
    
    This is idempotent - safe to call multiple times.
    """
    global _db_initialized
    
    if _db_initialized:
        logger.debug("Database already initialized, skipping")
        return
    
    # Import ORM models to register them with Base
    from src.infra.persistence import orm_models  # noqa: F401
    
    engine = get_engine()
    
    logger.info("Initializing database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    _db_initialized = True
    logger.info("Database tables initialized successfully")


async def close_db() -> None:
    """
    Close database connections and dispose of the engine.
    
    Call this during application shutdown.
    """
    global _engine, _session_factory, _db_initialized
    
    if _engine is not None:
        logger.info("Closing database connections...")
        await _engine.dispose()
        _engine = None
        _session_factory = None
        _db_initialized = False
        logger.info("Database connections closed")


# =============================================================================
# SQLITE OPTIMIZATION PRAGMAS
# =============================================================================

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    """
    Set SQLite-specific pragmas for better performance.
    
    These settings improve SQLite performance for typical workloads:
    - WAL mode for better concurrent reads
    - Larger cache for fewer disk reads
    - Memory temp store for faster temp table operations
    """
    settings = get_settings()
    
    if not settings.database_is_sqlite:
        return
    
    cursor = dbapi_conn.cursor()
    try:
        # Enable foreign key constraints
        cursor.execute("PRAGMA foreign_keys=ON")
        # Use Write-Ahead Logging for better concurrency
        cursor.execute("PRAGMA journal_mode=WAL")
        # Balance between safety and speed
        cursor.execute("PRAGMA synchronous=NORMAL")
        # 64MB cache size
        cursor.execute("PRAGMA cache_size=-64000")
        # Store temp tables in memory
        cursor.execute("PRAGMA temp_store=MEMORY")
        # 256MB memory-mapped I/O
        cursor.execute("PRAGMA mmap_size=268435456")
    finally:
        cursor.close()
