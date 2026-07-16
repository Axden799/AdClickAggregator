from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# The engine owns ONE connection pool to Postgres for the whole app — the DB
# equivalent of the single Redis client. Created once at import.
engine = create_async_engine(settings.database_url)

# A factory that produces AsyncSession objects bound to that engine.
# expire_on_commit=False keeps ORM objects usable after commit() (the async
# default would expire them and trigger surprise lazy-loads).
async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base every model inherits from (7b). Its `.metadata` is the
    schema Alembic autogenerate compares against the live database."""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: open a session for the request, hand it to the
    route, and guarantee it's closed afterward.

    This is a *yield* dependency (like `lifespan`, but per-request): everything
    before `yield` is setup, everything after is teardown.

    TODO (you):
      1. open a session:  async with async_session() as session:
      2. `yield session`  (hand it to the route)
      The `async with` block closes the session automatically when the request
      finishes — even if the route raises.
    """
    async with async_session() as session:
        yield session
