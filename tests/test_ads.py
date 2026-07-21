async def test_list_ads_serves_distinct_board(client, redis_client):
    # Act: GET /ads returns the whole board — every distinct ad, once — and
    # records one impression per ad onto the "impressions" stream.
    resp = await client.get("/ads")

    # Assert (you):
    #   1. resp.status_code == 200
    #   2. the body is a list of 4 ads, each with "ad_id" and "click_url":
    #        ads = resp.json()
    #        assert len(ads) == 4
    #   3. the ad_ids are DISTINCT (a real board, not random repeats):
    #        ids = [a["ad_id"] for a in ads]
    #        assert len(set(ids)) == 4
    #   4. one impression per ad landed on the stream (test DB starts empty):
    #        assert await redis_client.xlen("impressions") == 4
    assert resp.status_code == 200
    ads = resp.json()
    assert len(ads) == 4
    ids = [a["ad_id"] for a in ads]
    assert len(set(ids)) == 4
    assert await redis_client.xlen("impressions") == 4
