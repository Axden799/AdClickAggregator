from typing import Annotated

import redis.asyncio as redis
from fastapi import APIRouter, Depends, status

from app.dependencies import get_redis

router = APIRouter()


@router.get("/click", status_code=status.HTTP_202_ACCEPTED)
async def click(ad_id: int, r: Annotated[redis.Redis, Depends(get_redis)]):
    # Append the click onto the "clicks" Redis Stream (Redis auto-generates
    # the entry ID). XADD returns that ID, which we echo back as proof of write.
    entry_id = await r.xadd("clicks", {"ad_id": ad_id})

    return {"status": "accepted", "stream_id": entry_id}
