"""
Async DB session management.
The engine is built from settings.database_url, so switching between
SQLite (dev) and Supabase Postgres (prod) requires zero code change here -
only the .env DATABASE_URL changes.
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from config import settings

# SQLite needs this connect_arg; Postgres (asyncpg) ignores/doesn't need it.
connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args=connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    """FastAPI dependency - yields a DB session per request."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    """Create tables. For dev/SQLite quick-start only - production uses Alembic migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
