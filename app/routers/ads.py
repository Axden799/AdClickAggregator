import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_redis
from app.models import ClickMetric
from app.security import sign_impression

router = APIRouter(prefix="/ads", tags=["ads"])

# Longest window we'll serve in one request. 24h = 1440 one-minute buckets =
# 1440 ZSCOREs; the cap stops someone asking for a year (525k reads).
MAX_RANGE = timedelta(hours=24)

# In-memory serve list. Ids MUST match the seeded ad rows (app/seed.py) so
# every click's ad_id exists in the ad table before the flush writes a metric.
# (A later slice can read these straight from the DB.)
_FAKE_ADS = [
    {"id": 1, "image_url": "https://placehold.co/300x250?text=Buy+Widgets"},
    {"id": 2, "image_url": "https://placehold.co/300x250?text=Cloud+Sale"},
    {"id": 3, "image_url": "https://placehold.co/300x250?text=Fast+VPN"},
    {"id": 4, "image_url": "https://placehold.co/300x250?text=Learn+Python"},
]


@router.get("/serve")
async def serve_ad(r: Annotated[redis.Redis, Depends(get_redis)]):
    ad = random.choice(_FAKE_ADS)
    impression_id = uuid.uuid4().hex
    sig = sign_impression(impression_id, ad["id"])
    click_url = (
        f"/click?ad_id={ad['id']}&impression_id={impression_id}&sig={sig}"
    )
    # An impression = this ad was shown. Emit it onto the impressions stream so
    # the consumer counts it, exactly like /click emits onto the clicks stream.
    # TODO (you): XADD to the "impressions" stream with {"ad_id": ad["id"]}.
    #   await r.xadd("impressions", {"ad_id": ad["id"]})
    await r.xadd("impressions", {"ad_id": ad["id"]})
    return {"ad_id": ad["id"], "image_url": ad["image_url"], "click_url": click_url}


def _serve_one(ad: dict) -> dict:
    """Sign a fresh impression for one ad and build its click payload (no I/O)."""
    impression_id = uuid.uuid4().hex
    sig = sign_impression(impression_id, ad["id"])
    return {
        "ad_id": ad["id"],
        "image_url": ad["image_url"],
        "click_url": f"/click?ad_id={ad['id']}&impression_id={impression_id}&sig={sig}",
    }


@router.get("")
async def list_ads(r: Annotated[redis.Redis, Depends(get_redis)]):
    """Serve the whole ad board — every ad, once. Showing an ad IS an impression,
    so we record one per ad (the distinct-ad mirror of /serve). The landing page
    calls this so it shows 4 deterministic ads instead of random repeats."""
    board = [_serve_one(ad) for ad in _FAKE_ADS]
    for ad in board:
        await r.xadd("impressions", {"ad_id": ad["ad_id"]})
    return board


# --- Metrics query path --------------------------------------------------------

# The response is a per-minute timeseries. Declaring these as Pydantic models
# (response_model below) gives us validation + automatic JSON serialization —
# datetime fields come out as ISO 8601 strings for free.
class MetricPoint(BaseModel):
    timestamp: datetime  # start of the one-minute bucket, UTC
    clicks: int
    impressions: int
    ctr: float  # clicks / impressions (0.0 when there were no impressions)


class MetricsResponse(BaseModel):
    ad_id: str
    points: list[MetricPoint]


def _bucket_to_timestamp(minute: int) -> datetime:
    """Turn a minute-bucket integer back into the UTC datetime at its start —
    the inverse of the consumer's `ms // 1000 // 60`."""
    return datetime.fromtimestamp(minute * 60, tz=timezone.utc)


def _overlay(hot: float | None, cold: int) -> int:
    """Resolve one metric for one minute: the hot (Redis) value wins if present
    (it's the freshest live count), otherwise fall back to the cold (Postgres)
    value. Encapsulates the tier-priority rule so we apply it identically to
    clicks and impressions."""
    return int(hot) if hot is not None else cold


@router.get("/{ad_id}/metrics", response_model=MetricsResponse)
async def ad_metrics(
    ad_id: int,
    # 'from' is a Python keyword, so the parameter is 'from_' with an alias that
    # maps it back to ?from=... in the URL. FastAPI parses both query params into
    # datetime objects and 422s automatically if they aren't valid datetimes.
    from_: Annotated[datetime, Query(alias="from")],
    to: datetime,
    r: Annotated[redis.Redis, Depends(get_redis)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Guardrails
    if from_ > to:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "'from' must be before 'to'")
    if to - from_ > MAX_RANGE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "range too large (max 24h)")

    start = int(from_.timestamp()) // 60
    end = int(to.timestamp()) // 60

    # --- Cold tier: one query pulls every rolled-up minute in range from
    # Postgres — now BOTH counts. We key by minute-INTEGER (not datetime) so it
    # lines up with Redis's minute space, and store a (clicks, impressions) pair.
    result = await db.execute(
        select(
            ClickMetric.minute_bucket,
            ClickMetric.click_count,
            ClickMetric.impression_count,
        ).where(
            ClickMetric.ad_id == ad_id,
            ClickMetric.minute_bucket >= from_,
            ClickMetric.minute_bucket <= to,
        )
    )
    pg_counts = {
        int(minute_bucket.timestamp()) // 60: (clicks, impressions)
        for minute_bucket, clicks, impressions in result.all()
    }

    # --- Merge: Redis (hot) overlays Postgres (cold), for BOTH metrics.
    # Use _overlay(hot, cold) for each: it applies the "Redis wins, else
    # Postgres" rule. The cold fallback comes from pg_counts (default (0, 0)).
    #
    # TODO (you): for each minute in range(start, end + 1):
    #   1. pg_clicks, pg_impressions = pg_counts.get(minute, (0, 0))
    #   2. clicks = _overlay(await r.zscore(f"ad_clicks:{minute}", str(ad_id)),
    #                        pg_clicks)
    #   3. impressions = _overlay(
    #          await r.zscore(f"ad_impressions:{minute}", str(ad_id)),
    #          pg_impressions)
    #   4. ctr = clicks / impressions if impressions > 0 else 0.0   # avoid /0
    #   5. append MetricPoint(timestamp=_bucket_to_timestamp(minute),
    #             clicks=clicks, impressions=impressions, ctr=ctr)
    points: list[MetricPoint] = []
    for minute in range(start, end + 1):
        pg_clicks, pg_impressions = pg_counts.get(minute, (0, 0))
        clicks = _overlay(await r.zscore(f"ad_clicks:{minute}", str(ad_id)), pg_clicks)
        impressions = _overlay(
            await r.zscore(f"ad_impressions:{minute}", str(ad_id)),
            pg_impressions
        )
        ctr = clicks / impressions if impressions > 0 else 0.0
        points.append(
            MetricPoint(
                timestamp=_bucket_to_timestamp(minute),
                clicks=clicks,
                impressions=impressions,
                ctr=ctr)
            )

    return MetricsResponse(ad_id=str(ad_id), points=points)
