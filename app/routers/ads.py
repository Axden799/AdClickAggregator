import random
import uuid

from fastapi import APIRouter

from app.security import sign_impression

router = APIRouter(prefix="/ads", tags=["ads"])

# Temporary in-memory ad source. Stands in for the Ad table until the Postgres
# model slice — it lets us serve and sign impressions without a database yet.
_FAKE_ADS = [
    {"id": 1, "image_url": "https://placehold.co/300x250?text=Buy+Widgets"},
    {"id": 2, "image_url": "https://placehold.co/300x250?text=Cloud+Sale"},
]


@router.get("/serve")
async def serve_ad():
    ad = random.choice(_FAKE_ADS)
    impression_id = uuid.uuid4().hex
    sig = sign_impression(impression_id, ad["id"])
    click_url = (
        f"/click?ad_id={ad['id']}&impression_id={impression_id}&sig={sig}"
    )
    return {"ad_id": ad["id"], "image_url": ad["image_url"], "click_url": click_url}
