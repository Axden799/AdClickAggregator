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


def minute_bucket(entry_id: str) -> int:
    """Map a stream entry to its one-minute window label.

    Redis stream IDs look like '<milliseconds>-<seq>', e.g. '1783357460733-0'.
    The millisecond prefix IS the click's ingestion time. Floor it to a whole
    minute since the epoch — that integer is the bucket's name.

    TODO (you):
      1. split entry_id on '-', take the first part (the ms), wrap it in int()
      2. turn ms -> minutes: divide by 1000 (-> seconds), then by 60, using //
      3. return the resulting integer
    """
    timestamp = (int(entry_id.split('-')[0]) // 1000) // 60
    return timestamp


async def aggregate(r: redis.Redis, entry_id: str, fields: dict) -> None:
    """Count one click into its per-minute sorted set (this is 5b's core).

    TODO (you):
      1. minute = minute_bucket(entry_id)
      2. ad_id  = fields["ad_id"]
      3. ZINCRBY the bucket by 1 for that ad. The key is f"ad_clicks:{minute}".
         redis-py signature is zincrby(name, amount, value) — remember to await.
    """
    minute = minute_bucket(entry_id)
    resp = await r.zincrby(f"ad_clicks:{minute}", 1, fields["ad_id"])


async def consume_once(r: redis.Redis, block: int = 5000) -> int:
    """Run exactly one read -> aggregate -> ack cycle.

    Returns how many entries were processed (0 if the block timed out with
    nothing new). Pulling the loop body out of the infinite loop is what makes
    the consumer testable: a test can seed the stream, call consume_once once,
    and assert on the outcome — no unstoppable while-loop."""
    # '>' = entries never delivered to this group. Returns
    # [[stream, [(entry_id, {fields}), ...]]], or None on block timeout.
    resp = await r.xreadgroup(GROUP, CONSUMER, {STREAM: ">"}, count=10, block=block)
    if not resp:
        return 0

    processed = 0
    for _stream, entries in resp:
        for entry_id, fields in entries:
            await aggregate(r, entry_id, fields)
            # Ack only AFTER a successful aggregate: if aggregate raises, the
            # entry stays pending and replays on the next run (at-least-once).
            acked = await r.xack(STREAM, GROUP, entry_id)
            if not acked:
                log.warning("XACK returned 0 for %s — entry was not pending", entry_id)
            processed += 1
    return processed


async def consume() -> None:
    # socket_timeout=None: redis-py 8.0 defaults it to 5s, which would kill a
    # blocking XREADGROUP that sits idle waiting for the next click. The block=
    # argument alone governs how long we wait.
    r = redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=None)
    await ensure_group(r)
    log.info("consumer %r draining stream %r ...", CONSUMER, STREAM)

    while True:
        n = await consume_once(r)
        if n:
            log.info("aggregated %d click(s)", n)


if __name__ == "__main__":
    asyncio.run(consume())
