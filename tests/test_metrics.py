from datetime import datetime, timezone

from app.models import ClickMetric
from tests.conftest import TEST_AD_ID


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


# --- 7d: tiered read (Postgres cold path + Redis overlay) ---------------------
# These use TEST_AD_ID (the db_session fixture guarantees that ad exists) and a
# minute with NOTHING in Redis, so the value can only come from Postgres.
WHEN = datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc)


async def test_metrics_reads_cold_from_postgres(client, redis_client, db_session):
    # Arrange: a rolled-up row in Postgres only (Redis is flushed/empty). This
    # is the case the old Redis-only endpoint got WRONG (returned 0).
    db_session.add(ClickMetric(ad_id=TEST_AD_ID, minute_bucket=WHEN, click_count=42))
    await db_session.commit()

    resp = await client.get(
        f"/ads/{TEST_AD_ID}/metrics",
        params={"from": "2026-02-01T10:00:00Z", "to": "2026-02-01T10:00:00Z"},
    )

    # Assert (you): 200, one point, clicks == 42 (served from the cold tier).
    assert resp.status_code == 200
    points = resp.json()["points"]
    assert len(points) == 1 and points[0]["clicks"] == 42


async def test_metrics_redis_overlays_postgres(client, redis_client, db_session):
    # Arrange: SAME minute present in BOTH tiers with DIFFERENT values.
    # Postgres says 99, Redis says 7 — Redis is the fresher/live count.
    db_session.add(ClickMetric(ad_id=TEST_AD_ID, minute_bucket=WHEN, click_count=99))
    await db_session.commit()
    await redis_client.zincrby(f"ad_clicks:{_minute_of(WHEN)}", 7, str(TEST_AD_ID))

    resp = await client.get(
        f"/ads/{TEST_AD_ID}/metrics",
        params={"from": "2026-02-01T10:00:00Z", "to": "2026-02-01T10:00:00Z"},
    )

    # Assert (you): 200, one point, clicks == 7 (Redis wins the overlap, NOT 99).
    assert resp.status_code == 200
    points = resp.json()["points"]
    assert len(points) == 1 and points[0]["clicks"] == 7


# --- 8b: impressions + CTR ----------------------------------------------------


async def test_metrics_reports_impressions_and_ctr(client, redis_client, db_session):
    # Arrange: a cold row with 3 clicks out of 50 impressions -> CTR 0.06.
    db_session.add(ClickMetric(
        ad_id=TEST_AD_ID, minute_bucket=WHEN, click_count=3, impression_count=50,
    ))
    await db_session.commit()

    resp = await client.get(
        f"/ads/{TEST_AD_ID}/metrics",
        params={"from": "2026-02-01T10:00:00Z", "to": "2026-02-01T10:00:00Z"},
    )

    # Assert (you): 200, one point with clicks == 3, impressions == 50, and
    # ctr == 0.06 (3 / 50). p = resp.json()["points"][0]
    assert resp.status_code == 200
    points = resp.json()["points"]
    p = points[0]
    ctr = p["clicks"] / p["impressions"]
    assert len(points) == 1 and p["clicks"] == 3 and p["impressions"] == 50 and p["ctr"] == ctr


async def test_metrics_ctr_is_zero_with_no_impressions(client, redis_client, db_session):
    # TODO (you): a row with impression_count == 0 must NOT raise ZeroDivision —
    # it should report ctr == 0.0. Seed a ClickMetric with click_count=0,
    # impression_count=0 (or just impressions 0), query, and assert the point's
    # ctr == 0.0 and impressions == 0.
    db_session.add(ClickMetric(
        ad_id=TEST_AD_ID, minute_bucket=WHEN, click_count=5, impression_count=0,
    ))
    await db_session.commit()

    resp = await client.get(
        f"/ads/{TEST_AD_ID}/metrics",
        params={"from": "2026-02-01T10:00:00Z", "to": "2026-02-01T10:00:00Z"},
    )

    assert resp.status_code == 200
    points = resp.json()["points"]
    p = points[0]
    ctr = 0.0
    assert len(points) == 1 and p["clicks"] == 5 and p["impressions"] == 0 and p["ctr"] == ctr
