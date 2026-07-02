from typing import Annotated

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, status

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

    # Genuine click — append it onto the "clicks" stream (now carrying the
    # impression_id too, which Slice 3 will use for deduplication).
    entry_id = await r.xadd("clicks", {"ad_id": ad_id, "impression_id": impression_id})
    return {"status": "accepted", "stream_id": entry_id}
