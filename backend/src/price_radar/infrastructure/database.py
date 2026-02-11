"""Database configuration and session management."""

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from price_radar.infrastructure.config import settings

Base: Any = declarative_base()

database_url = settings.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
engine = create_async_engine(database_url, echo=settings.debug, future=True)

async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session."""
    async with async_session_maker() as session:
        yield session
