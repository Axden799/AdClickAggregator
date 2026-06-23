# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

Portfolio project implementing a simplified Ad Click Aggregator, based on the HelloInterview system design problem (https://www.hellointerview.com/learn/system-design/problem-breakdowns/ad-click-aggregator). Goal: demonstrate backend engineering skills for job applications — specifically Redis, async Python, and deployed production-like architecture.

## Stack

- **FastAPI + Pydantic** — async REST API and request validation
- **Redis Streams** — replaces Kafka; absorbs write spikes and decouples click ingestion from aggregation
- **Redis Sorted Sets** — pre-aggregated per-minute click counts per ad
- **Redis deduplication** — impression ID bloom filter / SET to prevent double-counting clicks
- **PostgreSQL + SQLAlchemy (async)** — persistent storage for ads, campaigns, and rolled-up metrics
- **asyncpg** — async PostgreSQL driver
- **Alembic** — database migrations
- **Docker Compose** — runs FastAPI app + Redis + PostgreSQL as a multi-service stack
- **pytest-asyncio + httpx** — async test suite

## Commands

```bash
# Activate venv
source venv/bin/activate

# Run the API (once main.py exists)
uvicorn app.main:app --reload

# Run tests
pytest
pytest -v
pytest tests/test_clicks.py -v          # single file
pytest tests/test_clicks.py::test_name  # single test

# Database migrations
alembic revision --autogenerate -m "describe change"
alembic upgrade head

# Freeze dependencies after any pip install
venv/bin/pip freeze > requirements.txt
```

## System Design (Simplified Portfolio Version)

**Click ingestion path:**
1. `POST /clicks` receives a click with `impression_id` and `ad_id`
2. Deduplication check: Redis SET/bloom filter rejects duplicate `impression_id`
3. Valid click written to Redis Stream (`XADD clicks *`)
4. HTTP 202 returned immediately — no synchronous DB write

**Aggregation consumer (background process):**
1. Reads from Redis Stream (`XREADGROUP`)
2. Increments Redis Sorted Set: `ZINCRBY ad_clicks:{minute_window} 1 {ad_id}`
3. Periodically flushes minute-window aggregates to PostgreSQL
4. Acknowledges stream messages (`XACK`) after successful flush

**Query path:**
1. `GET /ads/{ad_id}/metrics?from=...&to=...` returns click counts per minute
2. Served from PostgreSQL (rolled-up) or Redis Sorted Sets for recent windows

## Key Design Concepts to Understand

- **Redis Stream vs Kafka**: same append-only log semantics, consumer groups, at-least-once delivery — just single-node for portfolio scale
- **Impression ID deduplication**: each ad impression gets a unique ID before the user clicks; the click endpoint rejects any ID seen before (prevents double-counting from retries/bots)
- **Time windowing**: clicks bucketed by `floor(timestamp / 60)` into per-minute sorted set keys — keys expire after retention window
- **Consumer group pattern**: worker process tracks its own offset via `XREADGROUP`; crash recovery replays unacknowledged messages

## Learning Areas (New for This Project)

| Area | Status |
|---|---|
| FastAPI + Pydantic | New — Flask transfers well |
| async/await + asyncio | Must learn before starting |
| Redis Streams | Core of the project |
| Redis Sorted Sets + deduplication | Core of the project |
| Docker Compose multi-service | Partially known |
| Consumer process pattern | New |
| pytest-asyncio + httpx | Partially known |
| PostgreSQL + SQLAlchemy async | Mostly known |
| Alembic | Mostly known |
