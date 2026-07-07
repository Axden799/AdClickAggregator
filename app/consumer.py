import asyncio
import logging

import redis.asyncio as redis

from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
log = logging.getLogger("consumer")

STREAM = "clicks"
GROUP = "aggregators"
CONSUMER = "worker-1"


async def ensure_group(r: redis.Redis) -> None:
    """Create the consumer group if it doesn't already exist.

    mkstream=True also creates the stream, so the worker can boot before any
    click arrives. id='0' starts the group at the beginning of the stream, so
    we never skip clicks that landed before the worker started."""
    try:
        await r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
        log.info("created consumer group %r on stream %r", GROUP, STREAM)
    except redis.ResponseError as e:
        # BUSYGROUP = the group already exists; any other error is real.
        if "BUSYGROUP" not in str(e):
            raise
        log.info("consumer group %r already exists", GROUP)


def process(entry_id: str, fields: dict) -> None:
    # 5a: just log the drained click to prove the pipe works end to end.
    # 5b replaces this with real aggregation (time windowing + ZINCRBY).
    log.info("processed click %s: %s", entry_id, fields)


async def consume() -> None:
    # socket_timeout=None: redis-py 8.0 defaults it to 5s, which would kill a
    # blocking XREADGROUP that sits idle waiting for the next click. A long-lived
    # stream consumer must never socket-timeout while blocking — the block=
    # argument alone governs how long we wait.
    r = redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=None)
    await ensure_group(r)
    log.info("consumer %r draining stream %r ...", CONSUMER, STREAM)

    while True:
        # Read up to 10 new entries for this group, blocking up to 5s. '>' means
        # "entries never delivered to this group". Returns
        # [[stream, [(entry_id, {fields}), ...]]], or None on timeout.
        resp = await r.xreadgroup(GROUP, CONSUMER, {STREAM: ">"}, count=10, block=5000)

        if not resp:
            continue  # block timed out with no new entries — loop again

        for _stream, entries in resp:
            for entry_id, fields in entries:
                process(entry_id, fields)
                # Acknowledge: removes the entry from this group's pending list.
                acked = await r.xack(STREAM, GROUP, entry_id)
                if not acked:
                    log.warning("XACK returned 0 for %s — entry was not pending", entry_id)


if __name__ == "__main__":
    asyncio.run(consume())
