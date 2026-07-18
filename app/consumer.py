import asyncio
import logging
import time
from datetime import datetime, timezone

import redis.asyncio as redis
from sqlalchemy.dialects.postgresql import insert

from app.config import settings
from app.database import async_session
from app.models import ClickMetric

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
log = logging.getLogger("consumer")

STREAM = "clicks"
IMPRESSION_STREAM = "impressions"
GROUP = "aggregators"
CONSUMER = "worker-1"
# Set of minute buckets that have unflushed data (clicks OR impressions) — the
# flush loop's to-do list. Aggregators SADD a minute here whenever they touch it.
PENDING = "pending_minutes"


async def _create_group(r: redis.Redis, stream: str) -> None:
    """Create GROUP on one stream if it doesn't already exist. mkstream=True
    also creates the stream, so the worker can boot before any event arrives;
    id='0' starts at the beginning so we never skip events that predated us."""
    try:
        await r.xgroup_create(stream, GROUP, id="0", mkstream=True)
        log.info("created consumer group %r on stream %r", GROUP, stream)
    except redis.ResponseError as e:
        # BUSYGROUP = the group already exists; any other error is real.
        if "BUSYGROUP" not in str(e):
            raise
        log.info("consumer group %r already exists on %r", GROUP, stream)


async def ensure_group(r: redis.Redis) -> None:
    """Ensure the group exists on BOTH streams. XREADGROUP reads clicks and
    impressions together, and it errors (NOGROUP) if the group is missing on
    any stream it's asked to read — so both must be created up front."""
    await _create_group(r, STREAM)
    await _create_group(r, IMPRESSION_STREAM)


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
    await r.zincrby(f"ad_clicks:{minute}", 1, fields["ad_id"])
    # Mark this minute as having unflushed data, so the flush loop knows to
    # look at it. SADD is idempotent — touching the same minute many times
    # leaves exactly one entry.
    await r.sadd(PENDING, minute)


async def aggregate_impression(r: redis.Redis, entry_id: str, fields: dict) -> None:
    """Count one impression into its per-minute sorted set — the exact mirror
    of aggregate(), but into the ad_impressions:{minute} key.

    TODO (you): same three steps as aggregate(), just a different key:
      1. minute = minute_bucket(entry_id)
      2. ZINCRBY f"ad_impressions:{minute}" by 1 for fields["ad_id"]
      3. SADD the minute to PENDING (a minute needs flushing if EITHER a click
         OR an impression touched it — same shared to-do list).
    """
    minute = minute_bucket(entry_id)
    await r.zincrby(f"ad_impressions:{minute}", 1, fields["ad_id"])
    await r.sadd(PENDING, minute)


async def consume_once(r: redis.Redis, block: int = 5000) -> int:
    """Run exactly one read -> aggregate -> ack cycle across BOTH streams.

    Returns how many entries were processed (0 if the block timed out with
    nothing new). Pulling the loop body out of the infinite loop is what makes
    the consumer testable: a test can seed a stream, call consume_once once,
    and assert on the outcome — no unstoppable while-loop."""
    # Read new entries from both streams in one call. '>' = never-delivered.
    # Returns [[stream, [(entry_id, {fields}), ...]], ...] — one sub-list per
    # stream that had data — or None on block timeout.
    resp = await r.xreadgroup(
        GROUP, CONSUMER, {STREAM: ">", IMPRESSION_STREAM: ">"}, count=10, block=block
    )
    if not resp:
        return 0

    processed = 0
    for stream, entries in resp:
        for entry_id, fields in entries:
            # Route by which stream the entry came from.
            if stream == STREAM:
                await aggregate(r, entry_id, fields)
            else:
                await aggregate_impression(r, entry_id, fields)
            # Ack on the SAME stream we read from, only after a successful
            # aggregate (so a failure replays the entry — at-least-once).
            acked = await r.xack(stream, GROUP, entry_id)
            if not acked:
                log.warning("XACK returned 0 for %s — entry was not pending", entry_id)
            processed += 1
    return processed


async def flush_minute(r: redis.Redis, minute: int) -> int:
    """Copy one closed minute's counts from Redis into click_metric, then drop
    it from the pending set. Returns how many (ad, count) rows were written.

    The UPSERT (ON CONFLICT ... DO UPDATE) makes this idempotent: re-flushing
    the same minute overwrites the row rather than duplicating it, because the
    sorted set holds the authoritative total for that minute (not a delta)."""
    # Read both sorted sets for this minute as {ad_id: count} dicts. An ad may
    # appear in one, the other, or both (impressions without a click are common).
    clicks = dict(await r.zrange(f"ad_clicks:{minute}", 0, -1, withscores=True))
    impressions = dict(await r.zrange(f"ad_impressions:{minute}", 0, -1, withscores=True))

    ad_ids = set(clicks) | set(impressions)  # union: every ad touched this minute
    if ad_ids:
        bucket_ts = datetime.fromtimestamp(minute * 60, tz=timezone.utc)
        rows = [
            {
                "ad_id": int(ad_id),
                "minute_bucket": bucket_ts,
                "click_count": int(clicks.get(ad_id, 0)),
                "impression_count": int(impressions.get(ad_id, 0)),
            }
            for ad_id in ad_ids
        ]
        stmt = insert(ClickMetric).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["ad_id", "minute_bucket"],
            set_={
                "click_count": stmt.excluded.click_count,
                "impression_count": stmt.excluded.impression_count,
            },
        )
        async with async_session() as session:
            await session.execute(stmt)
            await session.commit()

    # Cross this minute off the to-do list. Do this AFTER the commit: if the
    # flush crashed above, the minute stays pending and is retried next tick.
    await r.srem(PENDING, minute)
    return len(ad_ids)


async def flush_once(r: redis.Redis, now: float | None = None) -> int:
    """One flush pass: flush every pending minute that has closed (ended more
    than flush_grace_seconds ago). Returns the number of minutes flushed.

    now is injectable so tests can pin the clock instead of sleeping.

    TODO (you): implement the watermark filter.
      1. now = now if now is not None else time.time()
      2. The newest minute-bucket we're allowed to flush:
             cutoff = int(now - settings.flush_grace_seconds) // 60
         (a minute is eligible only once it ended >= grace seconds ago)
      3. pending = await r.smembers(PENDING)   # a set of stringified ints
      4. for each m in pending:
             minute = int(m)
             if minute < cutoff:      # closed -> safe to flush
                 await flush_minute(r, minute)
                 count it
      5. return how many minutes you flushed.
    """
    now = now if now is not None else time.time()
    cutoff = int(now - settings.flush_grace_seconds) // 60
    pending = await r.smembers(PENDING)
    flushed = 0
    for m in pending:
        minute = int(m)
        if minute < cutoff:
            try:
                await flush_minute(r, minute)
                flushed += 1
            except Exception:
                # One bad minute (e.g. a bad ad_id) must not take down the
                # whole consumer. Log it and move on; flush_minute leaves the
                # minute in PENDING on failure, so the next tick retries it.
                log.exception("flush failed for minute %d — skipping", minute)
    return flushed


async def drain_loop(r: redis.Redis) -> None:
    """Forever: drain the stream into per-minute sorted sets."""
    while True:
        n = await consume_once(r)
        if n:
            log.info("aggregated %d click(s)", n)


async def flush_loop(r: redis.Redis) -> None:
    """Forever: every flush_interval_seconds, roll closed minutes to Postgres."""
    while True:
        flushed = await flush_once(r)
        if flushed:
            log.info("flushed %d closed minute(s) to postgres", flushed)
        await asyncio.sleep(settings.flush_interval_seconds)


async def consume() -> None:
    # socket_timeout=None: redis-py 8.0 defaults it to 5s, which would kill a
    # blocking XREADGROUP that sits idle waiting for the next click. The block=
    # argument alone governs how long we wait.
    r = redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=None)
    await ensure_group(r)
    log.info("consumer %r draining stream %r + flushing every %ds ...",
             CONSUMER, STREAM, settings.flush_interval_seconds)

    # Run the drain and the flush concurrently on the same event loop. gather
    # keeps both alive; if either raises, it propagates and the process exits.
    await asyncio.gather(drain_loop(r), flush_loop(r))


if __name__ == "__main__":
    asyncio.run(consume())
