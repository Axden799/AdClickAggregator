async def test_health_returns_ok(client):
    """Worked example: this is the shape every endpoint test follows —
    await a request on the async client, then assert on the response."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
