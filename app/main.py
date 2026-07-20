from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import settings
from app.database import engine
from app.routers import ads, clicks, health


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── startup ──
    # Open ONE Redis connection pool for the whole app.
    app.state.redis = redis.from_url(settings.redis_url, decode_responses=True)
    # Verify Postgres is reachable before serving traffic — fail fast if not.
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    yield
    # ── shutdown ── close both cleanly.
    await app.state.redis.aclose()
    await engine.dispose()


app = FastAPI(title="Ad Click Aggregator", lifespan=lifespan)

# Allow the React frontend (a different origin) to call this API from the
# browser. Without this, browsers block cross-origin requests. Our endpoints
# are GET-only and use no cookies, so no allow_credentials needed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(clicks.router)
app.include_router(ads.router)
