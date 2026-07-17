"""Seed the ad table with a small fixed set of ads.

Run once (idempotent) to populate Postgres so click_metric's foreign key has
ads to reference:

    python -m app.seed

The ids here MUST match the ads /ads/serve can serve, so every click's ad_id
exists in the ad table before the flush inserts a metric row for it.
"""

import asyncio

from sqlalchemy.dialects.postgresql import insert

from app.database import async_session
from app.models import Ad

ADS = [
    {"id": 1, "name": "Buy Widgets", "image_url": "https://placehold.co/300x250?text=Buy+Widgets", "destination_url": "https://example.com/widgets"},
    {"id": 2, "name": "Cloud Sale", "image_url": "https://placehold.co/300x250?text=Cloud+Sale", "destination_url": "https://example.com/cloud"},
    {"id": 3, "name": "Fast VPN", "image_url": "https://placehold.co/300x250?text=Fast+VPN", "destination_url": "https://example.com/vpn"},
    {"id": 4, "name": "Learn Python", "image_url": "https://placehold.co/300x250?text=Learn+Python", "destination_url": "https://example.com/python"},
]


async def seed() -> None:
    stmt = insert(Ad).values(ADS)
    # Re-running shouldn't error or duplicate: on a clashing id, refresh the
    # ad's mutable fields instead of inserting again.
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={
            "name": stmt.excluded.name,
            "image_url": stmt.excluded.image_url,
            "destination_url": stmt.excluded.destination_url,
        },
    )
    async with async_session() as session:
        await session.execute(stmt)
        await session.commit()
    print(f"seeded {len(ADS)} ads")


if __name__ == "__main__":
    asyncio.run(seed())
