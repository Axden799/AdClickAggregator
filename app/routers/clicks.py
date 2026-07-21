from typing import Annotated

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, status

from app.config import settings
from app.dependencies import get_redis
from app.security import verify_impression

router = APIRouter()


@router.get("/click", status_code=status.HTTP_202_ACCEPTED)
async def click(
    ad_id: int,
    impression_id: str,
    sig: str,
    r: Annotated[redis.Redis, Depends(get_redis)],
):
    # Reject forged or tampered clicks: the signature must match what we
    # would have produced at serve time for this (impression_id, ad_id).
    if not verify_impression(impression_id, ad_id, sig):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid or forged click signature")

    # Dedup (replay protection): atomically mark this impression as seen.
    # SET ... NX EX tells us whether WE were the first to record it.
    #   - key: f"imp:{impression_id}"
    #   - NX:  set only if the key does NOT already exist
    #   - EX:  expire after settings.dedup_ttl seconds (bounds memory)
    # TODO (you): call r.set(...) with nx + ex, capture the result in is_new.
    is_new = await r.set(
        f"imp:{impression_id}",
        "",
        nx=True,
        ex=settings.dedup_ttl
        )
    if not is_new:
        # Replay — already counted. Silent, indistinguishable no-op (no XADD).
        return {"status": "accepted"}

    # First time we've seen this impression — count it. maxlen+approximate keeps
    # the stream bounded: Redis trims old entries in whole blocks (the ~ form).
    await r.xadd(
        "clicks",
        {"ad_id": ad_id, "impression_id": impression_id},
        maxlen=settings.stream_maxlen,
        approximate=True,
    )
    return {"status": "accepted"}
