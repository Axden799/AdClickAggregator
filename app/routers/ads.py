import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.dependencies import get_redis
from app.security import sign_impression

router = APIRouter(prefix="/ads", tags=["ads"])

# Longest window we'll serve in one request. 24h = 1440 one-minute buckets =
# 1440 ZSCOREs; the cap stops someone asking for a year (525k reads).
MAX_RANGE = timedelta(hours=24)

# Temporary in-memory ad source. Stands in for the Ad table until the Postgres
# model slice — it lets us serve and sign impressions without a database yet.
_FAKE_ADS = [
    {"id": 1, "image_url": "https://placehold.co/300x250?text=Buy+Widgets"},
    {"id": 2, "image_url": "https://placehold.co/300x250?text=Cloud+Sale"},
]


@router.get("/serve")
async def serve_ad():
    ad = random.choice(_FAKE_ADS)
    impression_id = uuid.uuid4().hex
    sig = sign_impression(impression_id, ad["id"])
    click_url = (
        f"/click?ad_id={ad['id']}&impression_id={impression_id}&sig={sig}"
    )
    return {"ad_id": ad["id"], "image_url": ad["image_url"], "click_url": click_url}


# --- Metrics query path --------------------------------------------------------

# The response is a per-minute timeseries. Declaring these as Pydantic models
# (response_model below) gives us validation + automatic JSON serialization —
# datetime fields come out as ISO 8601 strings for free.
class MetricPoint(BaseModel):
    timestamp: datetime  # start of the one-minute bucket, UTC
    clicks: int


class MetricsResponse(BaseModel):
    ad_id: str
    points: list[MetricPoint]


def _bucket_to_timestamp(minute: int) -> datetime:
    """Turn a minute-bucket integer back into the UTC datetime at its start —
    the inverse of the consumer's `ms // 1000 // 60`."""
    return datetime.fromtimestamp(minute * 60, tz=timezone.utc)


@router.get("/{ad_id}/metrics", response_model=MetricsResponse)
async def ad_metrics(
    ad_id: int,
    # 'from' is a Python keyword, so the parameter is 'from_' with an alias that
    # maps it back to ?from=... in the URL. FastAPI parses both query params into
    # datetime objects and 422s automatically if they aren't valid datetimes.
    from_: Annotated[datetime, Query(alias="from")],
    to: datetime,
    r: Annotated[redis.Redis, Depends(get_redis)],
):
    # Guardrails
    if from_ > to:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "'from' must be before 'to'")
    if to - from_ > MAX_RANGE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "range too large (max 24h)")

    # TODO (you): build the per-minute timeseries. This is the mirror of the
    # consumer's write path — same minute-bucket math, but reading with ZSCORE.
    #   1. Convert the datetimes to minute buckets (same integer space the
    #      consumer used):
    #          start = int(from_.timestamp()) // 60
    #          end   = int(to.timestamp())   // 60
    #   2. For each minute in range(start, end + 1):
    #        - score = await r.zscore(f"ad_clicks:{minute}", str(ad_id))
    #        - an empty bucket returns None -> treat it as 0 clicks
    #        - append MetricPoint(timestamp=_bucket_to_timestamp(minute),
    #                             clicks=<the count>)
    #   3. Leave `points` as the list you built.
    points: list[MetricPoint] = []
    start = int(from_.timestamp()) // 60
    end = int(to.timestamp()) // 60
    for minute in range(start, end + 1):
        score = await r.zscore(f"ad_clicks:{minute}", str(ad_id))
        clicks = int(score) if score is not None else 0
        
        points.append(MetricPoint(timestamp=_bucket_to_timestamp(minute), clicks=clicks))

    return MetricsResponse(ad_id=str(ad_id), points=points)
