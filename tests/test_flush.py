from sqlalchemy import select

from app.consumer import PENDING, flush_once
from app.models import ClickMetric
from tests.conftest import TEST_AD_ID

# A fixed minute-bucket to seed. minute * 60 = epoch seconds, so this is just
# some concrete minute; its exact value doesn't matter, only that we control
# whether "now" is before or after its grace window.
MINUTE = 29_000_000
# Seconds at the very start of that minute (when time.time() == this, the
# minute has only just begun — nowhere near closed).
MINUTE_START = MINUTE * 60


async def _seed_minute(redis_client, minute: int, ad_id: int, count: int) -> None:
    """Put `count` clicks for `ad_id` into `minute`'s bucket + mark it pending,
    exactly as the consumer's aggregate() would."""
    await redis_client.zincrby(f"ad_clicks:{minute}", count, str(ad_id))
    await redis_client.sadd(PENDING, minute)


async def test_closed_minute_flushes_to_postgres(redis_client, db_session):
    # Arrange: 3 clicks in MINUTE for our ad.
    await _seed_minute(redis_client, MINUTE, TEST_AD_ID, 3)

    # Act: run the flush with the clock pinned WELL PAST the grace window
    # (a full day later), so MINUTE is definitely closed.
    flushed = await flush_once(redis_client, now=MINUTE_START + 86_400)

    # Assert (you):
    #   1. flushed == 1  (one minute was flushed)
    #   2. a click_metric row exists for (TEST_AD_ID, that minute) with count 3:
    #        rows = (await db_session.execute(
    #            select(ClickMetric).where(ClickMetric.ad_id == TEST_AD_ID)
    #        )).scalars().all()
    #        assert len(rows) == 1 and rows[0].click_count == 3
    #   3. the minute was removed from the pending set:
    #        assert await redis_client.smembers(PENDING) == set()
    assert flushed == 1
    rows = (await db_session.execute(
        select(ClickMetric).where(ClickMetric.ad_id == TEST_AD_ID)
    )).scalars().all()
    assert len(rows) == 1 and rows[0].click_count == 3
    assert await redis_client.smembers(PENDING) == set()


async def test_open_minute_is_not_flushed(redis_client, db_session):
    # TODO (you): seed MINUTE, but run flush_once with now pinned at
    # MINUTE_START (the minute has only just begun — inside the grace window).
    # Assert: flushed == 0, no click_metric rows exist, and the minute is STILL
    # pending (await redis_client.smembers(PENDING) == {str(MINUTE)}).
    # (Note: Redis returns set members as strings.)
    await _seed_minute(redis_client, MINUTE, TEST_AD_ID, 5)

    flushed = await flush_once(redis_client, now=MINUTE_START)

    assert flushed == 0
    rows = (await db_session.execute(
        select(ClickMetric).where(ClickMetric.ad_id == TEST_AD_ID)
    )).scalars().all()
    assert len(rows) == 0
    assert await redis_client.smembers(PENDING) == {str(MINUTE)}


async def test_reflush_overwrites_not_duplicates(redis_client, db_session):
    # TODO (you): prove the UPSERT is idempotent.
    #   1. seed MINUTE with 2 clicks, flush (past grace) -> 1 row, count 2
    #   2. seed the SAME minute again (aggregate re-adds it to PENDING) with 5
    #      more clicks so the bucket now totals 7, flush again
    #   3. assert there is STILL exactly ONE row for (TEST_AD_ID, minute), and
    #      its click_count is 7 (overwritten, not a second row).
    await _seed_minute(redis_client, MINUTE, TEST_AD_ID, 2)

    flushed = await flush_once(redis_client, now=MINUTE_START + 86_400)
    assert flushed == 1

    await _seed_minute(redis_client, MINUTE, TEST_AD_ID, 5)

    flushed = await flush_once(redis_client, now=MINUTE_START + 86_400)
    assert flushed == 1

    rows = (await db_session.execute(
        select(ClickMetric).where(ClickMetric.ad_id == TEST_AD_ID)
    )).scalars().all()
    assert len(rows) == 1 and rows[0].click_count == 7
