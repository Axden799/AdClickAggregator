from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI

from app.config import settings
from app.routers import ads, clicks, health


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── startup ── open ONE Redis connection pool for the whole app.
    app.state.redis = redis.from_url(settings.redis_url, decode_responses=True)
    yield
    # ── shutdown ── close it cleanly.
    await app.state.redis.aclose()


app = FastAPI(title="Ad Click Aggregator", lifespan=lifespan)

app.include_router(health.router)
app.include_router(clicks.router)
app.include_router(ads.router)
