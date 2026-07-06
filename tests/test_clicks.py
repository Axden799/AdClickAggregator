async def _serve_and_get_click_url(client) -> str:
    """Helper: serve an ad and return the signed click_url to follow.
    The response looks like {"ad_id":.., "image_url":.., "click_url":".."}."""
    resp = await client.get("/ads/serve")
    return resp.json()["click_url"]


async def test_genuine_click_is_counted(client, redis_client):
    # TODO (you): serve an ad (use the helper), follow the click_url once.
    # Assert the response is 202, AND assert the "clicks" stream grew to 1
    # entry. (redis_client.xlen("clicks") gives the count; it's async, so
    # await it. The test DB is flushed, so it starts at 0.)
    click_url = await _serve_and_get_click_url(client)
    resp = await client.get(click_url)
    assert resp.status_code == 202
    assert await redis_client.xlen("clicks") == 1


async def test_replayed_click_is_deduped(client, redis_client):
    # TODO (you): serve once, then follow the SAME click_url TWICE. Assert
    # both responses are 202, but the stream length is 1 (not 2) — the replay
    # was silently swallowed.
    click_url = await _serve_and_get_click_url(client)
    resp1 = await client.get(click_url)
    resp2 = await client.get(click_url)
    assert resp1.status_code == resp2.status_code == 202
    assert await redis_client.xlen("clicks") == 1


async def test_forged_signature_is_rejected(client):
    # TODO (you): GET /click with a made-up sig (e.g. impression_id=x,
    # sig=deadbeef, ad_id=1). Assert the response is 403.
    resp = await client.get("/click?ad_id=1&impression_id=x&sig=nothing")
    assert resp.status_code == 403
