# Ad Click Aggregator

**Live demo:** [ad-click-aggregator.vercel.app](https://ad-click-aggregator.vercel.app) &nbsp;·&nbsp; **API docs:** [/docs](https://agile-harmony-production-8121.up.railway.app/docs) &nbsp;·&nbsp; **Health:** [/health](https://agile-harmony-production-8121.up.railway.app/health)

> Frontend on Vercel, backend (API + aggregation worker + PostgreSQL + Redis) on Railway.

A real-time ad-click analytics pipeline built as a backend portfolio project. It ingests ad clicks at the write-spike-friendly rate of a real ad network, deduplicates them, aggregates them into per-minute windows in real time, and exposes the rolled-up metrics through an analytics API and dashboard.

The design is adapted from the [HelloInterview Ad Click Aggregator](https://www.hellointerview.com/learn/system-design/problem-breakdowns/ad-click-aggregator) system-design problem, deliberately scaled down to a **single-node, portfolio-grade deployment** (no Kafka, no Flink, no OLAP store, no load balancer, no sharding). Where the production design would reach for heavy distributed infrastructure, this project implements the same *patterns* with lighter tools and documents the scale-up path instead of building it. Knowing when **not** to reach for the heavy tool is part of the point.

---

## What it demonstrates

- **Redis Streams** as a durable, replayable event log (a single-node stand-in for Kafka)
- **Async Python consumer** doing windowed aggregation (a hand-rolled stand-in for Flink)
- **Redis Sorted Sets** as pre-aggregated, per-minute hot-read counters
- **Redis SET / bloom filter** for impression-ID deduplication
- **HMAC-signed impressions** to reject spoofed/forged clicks
- **FastAPI + async SQLAlchemy + asyncpg** for ingestion, querying, and durable rollups
- **A load simulator** so the write-spike absorption is actually visible in a demo

---

## Status

This README describes the **full target design**. The project is built incrementally — one thin vertical slice per commit — and roughly half the pipeline is implemented today:

- **Working now:** the serve endpoint with HMAC-signed impressions, click ingestion (HMAC verify → impression dedup → `XADD`), and the async aggregation consumer (consumer-group `XREADGROUP` → `ZINCRBY` into per-minute sorted sets → `XACK`) — all covered by a 10-test async suite.
- **In progress:** the metrics query endpoint (`GET /ads/{ad_id}/metrics`) — the Redis sorted-set read path.
- **Designed, not yet built:** PostgreSQL `Ad`/`ClickMetric` models + migrations, the consumer's flush to Postgres and sorted-set retention, the click→destination `302` redirect, the load simulator, the frontend, and the full multi-service Docker Compose stack.

See [Build status](#build-status) for the exact ledger. Note that some behaviors below describe the target (e.g. `/click` will `302`-redirect once the `Ad` model exists; today it returns `202 Accepted`).

---

## System overview

```
            SERVE                         CLICK (hot path)                AGGREGATION                 QUERY
┌──────────────┐   GET /ads/serve   ┌───────────────────┐  XADD   ┌─────────────────────┐      ┌──────────────────┐
│   Frontend   │ ─────────────────▶ │  FastAPI ingest   │ ──────▶ │  Redis Stream       │      │  Analytics page  │
│  (ad + chart)│ ◀───────────────── │  /click           │         │  (clicks)           │      │  GET /metrics    │
└──────────────┘   ad + signed      │  1. verify HMAC   │         └─────────┬───────────┘      └────────┬─────────┘
                   impression URL   │  2. dedup (SET)   │                   │ XREADGROUP                │
                                    │  3. XADD          │         ┌─────────▼───────────┐    recent    │
                                    │  4. 302 redirect  │         │  Async consumer     │ ◀── windows ─┤ Redis sorted sets
                                    └───────────────────┘         │  ZINCRBY per minute │              │
                                                                  │  flush every N sec  │    older     │
                                                                  └─────────┬───────────┘ ◀── windows ─┘ PostgreSQL
                                                                            │ flush
                                                                  ┌─────────▼───────────┐
                                                                  │   PostgreSQL        │
                                                                  │   click_metrics     │
                                                                  └─────────────────────┘
```

**Redis plays three distinct roles** in this system, which is worth making explicit:
1. **Stream** (`clicks`) — durable write buffer that absorbs spikes and decouples ingestion from aggregation
2. **Sorted Sets** (`ad_clicks:{minute}`) — pre-aggregated hot-read cache for recent windows
3. **SET / bloom filter** (`imp:{id}`) — deduplication store for impression IDs

---

## Entities

### `Ad` (PostgreSQL)
The pool of ads that can be served and clicked.

| Field | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `name` | str | Display/label for the ad |
| `image_url` | str | Placeholder creative shown in the frontend |
| `destination_url` | str | Where the click redirects (the ad "works") |
| `is_active` | bool | Only active ads are served |
| `created_at` | datetime | |

### `ClickMetric` (PostgreSQL — the rollup table)
Durable per-minute aggregates flushed from Redis by the consumer.

| Field | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `ad_id` | int FK → `Ad.id` | Indexed |
| `minute_bucket` | datetime | `floor(ts / 60)`; unique with `ad_id` |
| `click_count` | int | Aggregated clicks in that minute |

Unique index on `(ad_id, minute_bucket)` — this is the primary query and upsert key, and it makes Postgres act as the project's "OLAP" without a columnar store.

### Impression (ephemeral — not a DB table)
An impression is created at **serve** time and lives only in the signed click URL + the Redis dedup SET. It is never persisted to Postgres.

| Field | Origin | Purpose |
|---|---|---|
| `impression_id` | `uuid4()` at serve time | Unique per ad view; dedup key |
| `ad_id` | from served ad | Which ad was shown |
| `sig` | `HMAC(SECRET_KEY, impression_id + ad_id)` | Proves the click maps to an ad *we* served |

### Stream event (Redis Stream `clicks`)
A single click, post-validation: `{ ad_id, impression_id, ts }`.

---

## Data structures (sample values)

How the same click looks at each stage. One click on ad 1 at 10:00:

**Redis**

```python
# clicks — Stream (append-only log; id = <ms>-<seq>)
XRANGE clicks - +
→ [("1784500000000-0", {"ad_id": "1", "impression_id": "abc123"}), ...]

# ad_clicks:{minute} — Sorted Set (member = ad_id, score = count)
await r.zrange("ad_clicks:29742600", 0, -1, withscores=True)
→ [("1", 2.0), ("2", 1.0)]           # ad 1: 2 clicks, ad 2: 1 click, this minute
await r.zscore("ad_clicks:29742600", "1")  → 2.0   # or None if absent

# pending_minutes — Set (flush to-do list, minute-ints as strings)
await r.smembers("pending_minutes")  → {"29742600", "29742601"}

# imp:{id} — String (dedup marker; existence = "seen", empty value, TTL)
await r.get("imp:abc123")  → ""      # TTL ~86400s
```

**Postgres → the endpoint's merge dict**

```python
# raw query rows: list of (datetime, int) tuples
result.all()
→ [(datetime(2026, 3, 15, 10, 0, tzinfo=utc), 12), ...]

# pg_counts — dict keyed by minute-INTEGER (so it lines up with Redis)
→ {29742600: 12, 29742601: 30}
```

**API response** — `points` is a positional **list**, not keyed by minute:

```python
resp.json()
→ {"ad_id": "1", "points": [
     {"timestamp": "2026-03-15T10:00:00Z", "clicks": 12},
     {"timestamp": "2026-03-15T10:01:00Z", "clicks": 30},
   ]}
# access by position, then key:  resp.json()["points"][0]["clicks"] → 12
```

> `pg_counts` is a **dict** keyed by minute-integer (a lookup: is minute X present?);
> the response `points` is an ordered **list** for the client to plot. Same numbers,
> different container — don't index `points` by minute.

---

## Inputs and outputs

### `GET /ads/serve` — serve an ad (creates an impression)
**Output:**
```json
{
  "ad_id": 42,
  "image_url": "https://.../creative.png",
  "click_url": "/click?ad_id=42&impression_id=a1b2c3...&sig=9f8e7d..."
}
```

### `GET /click` — ingest a click (hot path)
**Input:** query params `ad_id`, `impression_id`, `sig`
**Behavior:** verify HMAC → dedup check → `XADD` → **302 redirect** to the ad's `destination_url`
**Output:** `302` redirect (browser follows to the advertiser). Invalid signature → `403`; duplicate impression → treated as a no-op (still redirects, never double-counts).

### `GET /ads/{ad_id}/metrics` — query analytics
**Input:** path `ad_id`; query `from`, `to` (ISO timestamps)
**Output:**
```json
{
  "ad_id": 42,
  "from": "2026-06-18T14:00:00Z",
  "to": "2026-06-18T14:05:00Z",
  "series": [
    { "minute": "2026-06-18T14:00:00Z", "clicks": 31 },
    { "minute": "2026-06-18T14:01:00Z", "clicks": 87 }
  ]
}
```
Recent minutes served from Redis sorted sets; older minutes from Postgres.

### `POST /simulate` — load generator (demo only)
**Input:** `{ "ad_id": 42, "count": 10000, "duplicate_rate": 0.1 }`
**Output:** `202 Accepted`; fires N synthetic signed clicks (a fraction duplicated to exercise dedup) so the dashboard visibly absorbs the spike.

---

## Functional requirements

1. Serve a random active ad with a signed, single-use impression.
2. Ingest a click: verify its signature, reject duplicates by impression ID, and redirect the user to the ad's destination.
3. Never lose a valid click and never double-count one.
4. Aggregate clicks into per-minute windows in near-real-time.
5. Persist rolled-up per-minute metrics durably.
6. Serve per-ad, per-minute analytics over an arbitrary time range.
7. Provide a load simulator to demonstrate spike absorption.

## Non-functional requirements (and how each is met at portfolio scale)

| Requirement | How it's met here | Production equivalent (documented, not built) |
|---|---|---|
| **Absorb write spikes** | Append-only `XADD` to a Redis Stream; ingestion returns immediately | Kafka, partitioned by `ad_id` |
| **Decouple ingest from processing** | Background async consumer drains the stream at its own pace | Kafka + Flink |
| **No lost clicks (durability)** | At-least-once via consumer group + `XACK`; crash replays the pending-entries list | Kafka offsets + Flink checkpoints |
| **No double counting (idempotency)** | Impression-ID dedup before `XADD`; HMAC rejects forged clicks | Same pattern, bloom filter at scale |
| **Low-latency reads** | Recent windows from Redis sorted sets; older from indexed Postgres | OLAP store (ClickHouse / Druid / Pinot) |
| **Real-time-ish metrics** | Consumer flush interval (e.g. every 5s) bounds end-to-end lag | Flink windowing + watermarks |
| **Scalability** | Single node sized for demo traffic | Horizontal: sharding, partitioning, load balancer |

---

## Program flow

### 1. Serve (impression creation)
1. `GET /ads/serve` picks a random active `Ad`.
2. Generate `impression_id = uuid4()`.
3. Compute `sig = HMAC(SECRET_KEY, impression_id + ad_id)`.
4. Return the ad creative + a `click_url` embedding `ad_id`, `impression_id`, `sig`.

### 2. Click ingestion (hot path — returns immediately)
1. `GET /click?ad_id=&impression_id=&sig=`.
2. **Verify HMAC** — recompute and compare; mismatch → `403` (forged click).
3. **Dedup** — `SET imp:{impression_id} "" NX EX <ttl>`. If the key already existed, it's a duplicate → skip the `XADD` (no double count).
4. **`XADD clicks *`** with `{ad_id, impression_id, ts}` — clean event onto the stream.
5. **`302` redirect** to the ad's `destination_url`.

### 3. Aggregation (background async consumer — the "Flink" stand-in)
1. `XREADGROUP` reads new clicks for the consumer group.
2. For each click: `ZINCRBY ad_clicks:{minute_bucket} 1 {ad_id}` where `minute_bucket = floor(ts / 60)`.
3. Every N seconds, **flush** each minute bucket to Postgres via upsert on `(ad_id, minute_bucket)`.
4. **`XACK`** the processed messages after a successful flush (at-least-once boundary).
5. Sorted-set keys expire after the retention window so Redis memory stays bounded.

### 4. Query (analytics)
1. `GET /ads/{ad_id}/metrics?from=&to=`.
2. **Recent** windows (still in Redis): read from sorted sets — hot path.
3. **Older** windows: read the `click_metrics` rollup table in Postgres.
4. Merge into a single per-minute series; frontend renders the chart.

---

## Technologies and packages

| Package | Role in this project |
|---|---|
| **fastapi** / **starlette** | Async REST API: `/ads/serve`, `/click`, `/metrics`, `/simulate` |
| **uvicorn** (+ **uvloop**, **httptools**) | ASGI server running the app; uvloop/httptools for throughput |
| **fastapi-cli** | Provides the `fastapi dev` / `fastapi run` commands (installed via `fastapi[standard]`) |
| **pydantic** / **pydantic-settings** | Request/response validation; typed config from `.env` |
| **python-dotenv** | Loads local secrets (`SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`) |
| **redis** (`redis.asyncio`) | All three Redis roles: Streams, Sorted Sets, dedup SET/bloom |
| **SQLAlchemy** (async) | ORM for `Ad` and `ClickMetric` |
| **asyncpg** | Async PostgreSQL driver under SQLAlchemy |
| **greenlet** | Required bridge for async SQLAlchemy |
| **alembic** (+ **mako**) | Schema migrations |
| **anyio** | Async foundation under FastAPI/httpx |
| **pytest** / **pytest-asyncio** / **httpx** | Async test suite; in-process API testing |
| **hmac** / **hashlib** (stdlib) or **itsdangerous** | Impression signing/verification |
| **Docker Compose** | Runs FastAPI app + Redis + PostgreSQL as one stack |

The API stack was installed with `fastapi[standard]`, which also bundles **python-multipart**, **jinja2**, and **email-validator**. These backend-only endpoints don't currently use them — they're present as part of the standard bundle and available if needed later.

Frontend is intentionally minimal (a clickable ad + an analytics chart page) — this is a backend showcase, not a UI project.

---

## Tradeoffs at portfolio scale

Every "heavy" component from the production design is deliberately replaced with a single-node equivalent. The point is to demonstrate the *patterns* and the *judgment*, not to operate distributed infrastructure for demo traffic.

### Redis Streams instead of Kafka
Redis Streams gives the same model that matters here — append-only log, consumer groups, per-consumer offsets, at-least-once delivery, replay of unacknowledged messages — on a single node with no cluster to operate. Kafka's wins (multi-broker durability, partitioned horizontal scale, huge retention) are irrelevant at demo volume.
**At scale:** Redis Streams → Kafka, partitioned by `ad_id`.

### Hand-rolled async consumer instead of Flink
A ~100-line asyncio consumer (`XREADGROUP` → `ZINCRBY` → flush → `XACK`) does exactly what a Flink job would here, and makes the windowing logic explicit and explainable rather than hidden behind a framework. Flink is a JVM cluster (JobManager + TaskManagers) built for millions of events/sec with distributed checkpointing — overkill that would also drag the design back toward Kafka and blow the single-node deploy budget.
**At scale:** async consumer → Flink with windowing + watermarks for out-of-order events.

### PostgreSQL instead of an OLAP store
With a unique index on `(ad_id, minute_bucket)`, Postgres answers per-ad/per-minute range queries instantly at this volume — it *is* the OLAP layer here. Columnar analytics stores earn their keep over billions of rows, not thousands.
**At scale:** rollup table → ClickHouse / Druid / Pinot.

### No load balancer
A single Uvicorn process handles demo traffic. A load balancer only matters once you run multiple app replicas for availability/throughput.
**At scale:** add a load balancer in front of N stateless FastAPI replicas (the app holds no local state — all state is in Redis/Postgres — so it scales horizontally cleanly).

### No sharding / Redis Cluster
One Redis node holds the stream, sorted sets, and dedup keys. Sharding splits keys across nodes for capacity this project will never reach.
**At scale:** shard/partition by `ad_id` (same key as Kafka partitioning) so each ad's clicks, counters, and dedup state colocate and stay ordered.

### Dedup SET instead of a bloom filter
An exact Redis SET with per-key TTL is simple and correct at this scale. A bloom filter trades a tiny false-positive rate for large memory savings once impression volume is huge.
**At scale:** `SET imp:{id} NX EX` → Redis bloom filter (`BF.ADD`).

---

## Commands

```bash
# Activate venv
source venv/bin/activate

# Run the API
uvicorn app.main:app --reload

# Run the aggregation consumer (separate process)
python -m app.consumer

# Seed the ad table (idempotent; run once so click_metric's FK has ads)
python -m app.seed

# Tests
pytest
pytest tests/test_clicks.py -v

# Database migrations
alembic revision --autogenerate -m "describe change"
alembic upgrade head

# Bring up the full stack
docker compose up

# Freeze dependencies after any pip install
venv/bin/pip freeze > requirements.txt
```

### Inspecting state

```bash
# --- Redis (all via: docker compose exec redis redis-cli <cmd>) ---
SMEMBERS pending_minutes                 # minutes with unflushed data (flush to-do list)
KEYS 'ad_clicks:*'                       # which per-minute count buckets exist
ZRANGE ad_clicks:<minute> 0 -1 WITHSCORES  # a minute's counts (member=ad_id, score=clicks)
XLEN clicks                              # raw click-stream length
XRANGE clicks - +                        # dump the raw click stream
KEYS 'imp:*'                             # dedup markers (impression ids seen)
XINFO GROUPS clicks                      # consumer-group state
XPENDING clicks aggregators              # unacked (pending) stream entries

# --- Postgres (all via: docker compose exec postgres psql -U adclick -d adclick -c "<sql>") ---
\dt                                      # list tables
SELECT id, name FROM ad;                 # seeded ads
SELECT ad_id, minute_bucket, click_count FROM click_metric ORDER BY minute_bucket;  # roll-ups
```

## Environment variables (`.env`, not committed)

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | HMAC signing of impressions |
| `DATABASE_URL` | PostgreSQL connection (`postgresql+asyncpg://...`) |
| `REDIS_URL` | Redis connection |
| `DEDUP_TTL` | Seconds an impression ID is remembered for dedup |
| `FLUSH_INTERVAL` | Seconds between consumer flushes to Postgres |
| `WINDOW_RETENTION` | Seconds before a sorted-set minute bucket expires |

---

## Build status

| Stage | Status |
|---|---|
| FastAPI app (`app/main.py`, lifespan-managed Redis, routers) | Done |
| Serve endpoint + HMAC impression signing | Done |
| Click ingestion (verify → dedup → XADD) | Done |
| Aggregation consumer (XREADGROUP → ZINCRBY sorted sets → XACK) | Done |
| Data model (`Ad`, `ClickMetric`) + Alembic migrations | Done |
| Consumer flush to Postgres (watermark) + sorted-set retention TTL | Done |
| Impression counting + CTR | Done |
| Metrics query — tiered read (Redis hot overlays Postgres cold) | Done |
| Stream trimming (bounded raw-event streams) | Done |
| Load simulator (`app/simulate.py`) | Done |
| React frontend — landing board + dashboard table + per-minute chart | Done |
| Full Docker Compose stack (app + consumer + Redis + Postgres) | Done |
| Async test suite (23 tests) | Done |
| **Deployed** — Vercel (frontend) + Railway (API, worker, Postgres, Redis) | Done |
| Click → destination `302` redirect | Not started (returns 202; deliberate) |
