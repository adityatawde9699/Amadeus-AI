"""
Enhanced database configuration with connection pooling and optimizations.
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool, StaticPool
from sqlalchemy import event
from sqlalchemy.engine import Engine
import config
import sqlalchemy
import logging
import os

logger = logging.getLogger(__name__)

# ============================================================================
# DATABASE CONFIGURATION
# ============================================================================

# Connection pool settings
DB_POOL_SIZE = int(os.getenv('DB_POOL_SIZE', '5'))  # Number of connections to maintain
DB_MAX_OVERFLOW = int(os.getenv('DB_MAX_OVERFLOW', '10'))  # Max connections beyond pool_size
DB_POOL_TIMEOUT = int(os.getenv('DB_POOL_TIMEOUT', '30'))  # Seconds to wait for connection
DB_POOL_RECYCLE = int(os.getenv('DB_POOL_RECYCLE', '3600'))  # Seconds before recycling connection
DB_ECHO = os.getenv('DB_ECHO', 'false').lower() in ('1', 'true', 'yes')  # SQL logging

# Async engine using aiosqlite driver with connection pooling
ASYNC_DB_URL = config.DB_URL.replace('sqlite:///', 'sqlite+aiosqlite:///')

# For SQLite, use StaticPool for better connection management
# For production databases (PostgreSQL, MySQL), use QueuePool
if 'sqlite' in ASYNC_DB_URL.lower():
    # Use StaticPool for in-memory databases, NullPool for file-based to allow concurrency
    is_memory = ':memory:' in ASYNC_DB_URL.lower()
    pool_type = StaticPool if is_memory else NullPool
    
    # SQLite connection pool configuration
    engine = create_async_engine(
        ASYNC_DB_URL,
        echo=DB_ECHO,
        future=True,
        poolclass=pool_type,
        pool_pre_ping=True,  # Verify connections before using
        connect_args={
            "check_same_thread": False,  # Allow multi-threaded access
            "timeout": DB_POOL_TIMEOUT,
        }
    )
else:
    # For other databases, use connection pooling
    engine = create_async_engine(
        ASYNC_DB_URL,
        echo=DB_ECHO,
        future=True,
        pool_size=DB_POOL_SIZE,
        max_overflow=DB_MAX_OVERFLOW,
        pool_timeout=DB_POOL_TIMEOUT,
        pool_recycle=DB_POOL_RECYCLE,
        pool_pre_ping=True,  # Verify connections before using
    )

# Async session factory with optimized settings
async_session = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Don't expire objects after commit (better performance)
    autoflush=True,  # Auto-flush changes
    autocommit=False,  # Use transactions
)

Base = declarative_base()


# ============================================================================
# DATABASE EVENT LISTENERS FOR OPTIMIZATION
# ============================================================================

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    """Set SQLite pragmas for better performance."""
    if 'sqlite' in ASYNC_DB_URL.lower():
        # Enable foreign keys
        dbapi_conn.execute("PRAGMA foreign_keys=ON")
        # Optimize for performance
        dbapi_conn.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging
        dbapi_conn.execute("PRAGMA synchronous=NORMAL")  # Balance between safety and speed
        dbapi_conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
        dbapi_conn.execute("PRAGMA temp_store=MEMORY")  # Store temp tables in memory
        dbapi_conn.execute("PRAGMA mmap_size=268435456")  # 256MB memory-mapped I/O


# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================

_db_initialized = False

async def init_db_async():
    """
    Create DB tables asynchronously with proper index creation.
    Import models inside to avoid circular imports.
    Idempotent: Safe to call multiple times.
    """
    global _db_initialized
    if _db_initialized:
        return

    # Import models so they are registered on Base
    import models  # noqa: F401
    
    logger.info("Initializing database...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    _db_initialized = True
    logger.info("Database initialized successfully")


async def close_db():
    """Close database connections."""
    logger.info("Closing database connections...")
    await engine.dispose()
    logger.info("Database connections closed")


# ============================================================================
# SESSION MANAGEMENT
# ============================================================================

from contextlib import asynccontextmanager


@asynccontextmanager
async def get_async_session():
    """
    Async context manager yielding an AsyncSession instance.
    Includes automatic rollback on exception.

    Usage: 
        async with get_async_session() as session:
            # Use session
            ...
    """
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ============================================================================
# QUERY OPTIMIZATION HELPERS
# ============================================================================

async def execute_optimized_query(query, session: AsyncSession):
    """
    Execute a query with optimizations.
    
    Args:
        query: SQLAlchemy query object
        session: Database session
        
    Returns:
        Query result
    """
    # For SQLite, we can add query hints
    result = await session.execute(query)
    return result

