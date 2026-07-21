"""Traffic simulator — keeps a running deployment populated with organic-looking
data so a demo link always shows recent activity.

In a loop, it serves a burst of impressions and clicks a small random fraction
of them (realistic low CTR). It only uses the public HTTP API — the same signed
serve -> click flow a real browser follows — so it also exercises the full path.

    python -m app.simulate                          # against localhost:8000
    AD_API_URL=https://your-api python -m app.simulate   # against a deployed API
"""

import asyncio
import logging
import os
import random

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s simulate: %(message)s")
log = logging.getLogger("simulate")

# Where to send traffic. Defaults to local dev; override to hit the deployed API.
BASE_URL = os.environ.get("AD_API_URL", "http://localhost:8000")

# --- Tuning dials -------------------------------------------------------------
# Impressions vastly outnumber clicks, so CTR stays realistic.
IMPRESSIONS_PER_BURST = (5, 20)   # random count served each burst
CLICK_PROBABILITY = 0.08          # ~8% of impressions get clicked
BURST_INTERVAL = (30, 90)       # seconds to wait between bursts (jittered)


async def burst(client: httpx.AsyncClient) -> None:
    """One burst: serve N impressions, click a random fraction of them."""
    n = random.randint(*IMPRESSIONS_PER_BURST)
    clicks = 0
    for _ in range(n):
        # Serve an ad -> records an impression, returns a signed click_url.
        ad = (await client.get(f"{BASE_URL}/ads/serve")).json()
        # Click only a small fraction -> realistic low CTR.
        if random.random() < CLICK_PROBABILITY:
            await client.get(f"{BASE_URL}{ad['click_url']}")
            clicks += 1
    log.info("burst: %d impressions, %d clicks", n, clicks)


async def run() -> None:
    log.info("simulating traffic against %s", BASE_URL)
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            try:
                await burst(client)
            except Exception:
                # A transient network blip shouldn't kill the bot — log and
                # keep going (same resilience principle as the flush loop).
                log.exception("burst failed — retrying next tick")
            await asyncio.sleep(random.uniform(*BURST_INTERVAL))


if __name__ == "__main__":
    asyncio.run(run())
