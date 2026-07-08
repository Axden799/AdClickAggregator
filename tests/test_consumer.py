from app.consumer import (
    GROUP,
    STREAM,
    consume_once,
    ensure_group,
    minute_bucket,
)

# minute_bucket is a pure function — no Redis, no async. Test it plainly.


def test_minute_bucket_floors_to_the_minute():
    # Stream IDs are '<ms>-<seq>'. 1783357460733 ms -> 1783357460 s -> minute
    # 29722624. Two entries 15s apart share a bucket; the next minute rolls over.
    # TODO (you): assert minute_bucket returns the same int for two IDs in the
    # same minute, and a different int once the timestamp crosses 60s.
    assert minute_bucket("60000-0") == 1      # 60s  -> minute 1
    assert minute_bucket("90000-0") == 1      # 90s  -> still minute 1 (floored)
    assert minute_bucket("120000-0") == 2     # 120s -> minute 2


async def test_click_is_aggregated(redis_client):
    # Arrange: create the group, then put ONE click on the stream. xadd RETURNS
    # the new entry_id (e.g. '1783...-0') — capture it, because you need it to
    # know which minute bucket the click should have landed in.
    await ensure_group(redis_client)
    entry_id = await redis_client.xadd(STREAM, {"ad_id": "7", "impression_id": "abc"})

    # Act: run exactly one read -> aggregate -> ack cycle. block=100 keeps the
    # test snappy if there were somehow nothing to read.

    # Assert (you):
    #   1. processed == 1  (one entry was drained)
    #   2. the click landed in the right bucket at count 1:
    #        key = f"ad_clicks:{minute_bucket(entry_id)}"
    #        await redis_client.zscore(key, "7")  should equal 1
    #   3. (bonus) nothing is left unacked. XPENDING's summary form returns a
    #      dict; the 'pending' key should be 0:
    #        pend = await redis_client.xpending(STREAM, GROUP)
    #        assert pend["pending"] == 0
    pend = await redis_client.xpending(STREAM, GROUP)

    assert await consume_once(redis_client, block=100) == 1
    assert await redis_client.zscore(f"ad_clicks:{minute_bucket(entry_id)}", "7") == 1
    assert pend["pending"] == 0


async def test_second_click_same_minute_increments_to_2(redis_client):
    # TODO (you): add TWO clicks for the same ad in the same run, drain them,
    # and assert the bucket's score for that ad is 2 — proof ZINCRBY accumulates
    # rather than overwrites. (Both xadds happen within the same minute, so they
    # share a bucket. Use minute_bucket on either returned entry_id for the key.)
    await ensure_group(redis_client)
    entry_id = await redis_client.xadd(STREAM, {"ad_id": "12", "impression_id": "ahc"})
    entry_id = await redis_client.xadd(STREAM, {"ad_id": "12", "impression_id": "ahc"})

    assert await consume_once(redis_client, block=100) == 2
    score = await redis_client.zscore(f"ad_clicks:{minute_bucket(entry_id)}", "12")
    assert score == 2
