import redis.asyncio as redis
from fastapi import Request


async def get_redis(request: Request) -> redis.Redis:
    """Hand out the shared Redis client that lifespan opened at startup.

    The client (a connection pool) is created once for the whole app and
    stored on app.state; here we just read it back so routes can inject it
    with Depends(get_redis). Nothing to open or close per request."""
    return request.app.state.redis
