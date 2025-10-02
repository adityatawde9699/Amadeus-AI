from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
import config
import sqlalchemy

# Async engine using aiosqlite driver
ASYNC_DB_URL = config.DB_URL.replace('sqlite:///', 'sqlite+aiosqlite:///')
engine = create_async_engine(ASYNC_DB_URL, echo=False, future=True)

# Async session factory using async_sessionmaker (accepts AsyncEngine)
async_session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


async def init_db_async():
    """Create DB tables asynchronously. Import models inside to avoid circular imports."""
    # Import models so they are registered on Base
    import models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


from contextlib import asynccontextmanager


@asynccontextmanager
async def get_async_session():
    """Async context manager yielding an AsyncSession instance.

    Usage: async with get_async_session() as session:
               ...
    """
    async with async_session() as session:
        yield session

