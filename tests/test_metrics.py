from datetime import datetime, timezone


def _minute_of(dt: datetime) -> int:
    """The bucket integer for a datetime — the same math the endpoint uses."""
    return int(dt.timestamp()) // 60


async def test_metrics_counts_seeded_clicks(client, redis_client):
    # Arrange: drop 3 clicks for ad 7 into a known minute's sorted set, exactly
    # as the consumer would (ZINCRBY into ad_clicks:{minute}). We seed Redis
    # directly so this test covers ONLY the read path, not the whole pipeline.
    when = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    await redis_client.zincrby(f"ad_clicks:{_minute_of(when)}", 3, "7")

    # Act: query a one-minute window covering that instant (from == to -> a
    # single bucket -> a single point).
    resp = await client.get(
        "/ads/7/metrics",
        params={"from": "2026-01-01T10:00:00Z", "to": "2026-01-01T10:00:00Z"},
    )

    # Assert (you):
    #   1. resp.status_code == 200
    #   2. the response has exactly one point, and its clicks == 3
    #      data = resp.json(); data["points"] is the list; each item has
    #      "timestamp" and "clicks".
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["points"]) == 1
    assert data["points"][0]["clicks"] == 3


async def test_metrics_empty_range_is_all_zeros(client, redis_client):
    # TODO (you): query a window where NOTHING was seeded (redis_client is
    # flushed, so every bucket is empty). Assert 200, and that every point's
    # clicks == 0. A ~3-minute window gives a few zero points to check.
    # (Tip: all(p["clicks"] == 0 for p in resp.json()["points"]).)
    resp = await client.get(
        "/ads/7/metrics",
        params={"from": "2026-01-01T10:00:00Z", "to": "2026-01-01T10:03:00Z"},
    )
    assert resp.status_code == 200
    points = resp.json()["points"]
    assert all(p["clicks"] == 0 for p in points)


async def test_metrics_rejects_backwards_range(client):
    # TODO (you): from AFTER to -> 400. No seeding needed — the guard fires
    # before any Redis read.
    resp = await client.get(
        "/ads/7/metrics",
        params={"from": "2026-01-01T11:00:00Z", "to": "2026-01-01T10:00:00Z"},
    )
    assert resp.status_code == 400


async def test_metrics_rejects_too_large_range(client):
    # TODO (you): a range longer than 24h -> 400 (e.g. from 2026-01-01 to
    # 2026-01-03).
    resp = await client.get(
        "/ads/7/metrics",
        params={"from": "2026-01-01T00:00:00Z", "to": "2026-01-03T00:00:00Z"},
    )
    assert resp.status_code == 400
