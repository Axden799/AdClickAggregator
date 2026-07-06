import pytest
import redis.asyncio as redis
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_redis
from app.main import app

# db 15 = an isolated logical database, separate from dev (db 0). Tests never
# touch your real data, and we FLUSHDB it around every test for determinism.
TEST_REDIS_URL = "redis://localhost:6379/15"


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
