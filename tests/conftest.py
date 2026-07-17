import pytest
import redis.asyncio as redis
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert

from app.database import async_session, engine
from app.dependencies import get_redis
from app.main import app
from app.models import Ad, ClickMetric

# db 15 = an isolated logical database, separate from dev (db 0). Tests never
# touch your real data, and we FLUSHDB it around every test for determinism.
TEST_REDIS_URL = "redis://localhost:6379/15"

# Ad id used by the flush tests. The fixture guarantees it exists so the
# click_metric FK is satisfied.
TEST_AD_ID = 1


@pytest.fixture(autouse=True)
async def _dispose_engine():
    """pytest-asyncio gives each test a fresh event loop, but the module-global
    engine pools asyncpg connections bound to the loop that created them. Reusing
    a pooled connection on a later test's loop raises 'attached to a different
    loop'. Disposing the pool after each test forces the next test to open fresh
    connections on its own loop."""
    yield
    await engine.dispose()


@pytest.fixture
async def redis_client():
    """A Redis client bound to the isolated test DB. Flushed before and after
    each test so every test starts from a clean, known state."""
    client = redis.from_url(TEST_REDIS_URL, decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def db_session():
    """A session against the dev Postgres for the flush tests.

    Cleans click_metric before and after each test (so counts are deterministic)
    and guarantees a TEST_AD_ID ad row exists so the click_metric FK is happy.
    Unlike Redis, we don't have an isolated logical DB here — we just scope the
    cleanup to the rollup table this suite touches. Requires Postgres running."""
    async with async_session() as session:
        await session.execute(delete(ClickMetric))
        # Ensure the referenced ad exists (idempotent).
        stmt = insert(Ad).values(
            id=TEST_AD_ID, name="test", image_url="x", destination_url="x"
        )
        await session.execute(stmt.on_conflict_do_nothing(index_elements=["id"]))
        await session.commit()
        yield session
        await session.execute(delete(ClickMetric))
        await session.commit()


@pytest.fixture
async def client(redis_client):
    """An async HTTP client that drives the app in-process (no live server).

    We override get_redis so every route uses the test Redis (db 15) instead
    of the dev connection — this is exactly why routes take Redis via Depends
    rather than importing a global: it makes them swappable in tests."""
    app.dependency_overrides[get_redis] = lambda: redis_client
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
