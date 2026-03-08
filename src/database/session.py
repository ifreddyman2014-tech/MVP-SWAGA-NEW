"""Database session management for SQLAlchemy 2.0 async."""

import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from ..config import settings
from .models import Base

logger = logging.getLogger(__name__)

# Create async engine
engine = create_async_engine(
    settings.database_url,
    echo=settings.log_level == "DEBUG",
    poolclass=NullPool,  # For production, use proper pooling
    pool_pre_ping=True,
)

# Create async session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for FastAPI/aiogram to get database session.

    Usage in FastAPI:
        @app.get("/users")
        async def get_users(session: AsyncSession = Depends(get_session)):
            ...

    Usage in aiogram middleware:
        data["session"] = await anext(get_session())
    """
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database - create all tables and run column migrations."""
    logger.info("Initializing database...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_add_sub_token(conn)
    logger.info("Database initialized successfully")


async def _migrate_add_sub_token(conn) -> None:
    """Add sub_token column to subscriptions if it doesn't exist yet."""
    from sqlalchemy import text
    result = await conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='subscriptions' AND column_name='sub_token'"
    ))
    if result.fetchone():
        return  # Already migrated

    logger.info("Migration: adding sub_token to subscriptions...")
    await conn.execute(text(
        "ALTER TABLE subscriptions ADD COLUMN sub_token VARCHAR(36)"
    ))
    # Fill existing rows with unique UUIDs
    await conn.execute(text(
        "UPDATE subscriptions SET sub_token = gen_random_uuid()::text WHERE sub_token IS NULL"
    ))
    await conn.execute(text(
        "ALTER TABLE subscriptions ALTER COLUMN sub_token SET NOT NULL"
    ))
    await conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_subscriptions_sub_token ON subscriptions(sub_token)"
    ))
    logger.info("Migration: sub_token added successfully")


async def close_db() -> None:
    """Close database connections."""
    logger.info("Closing database connections...")
    await engine.dispose()
    logger.info("Database connections closed")
