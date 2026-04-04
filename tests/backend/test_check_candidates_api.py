import pytest


@pytest.mark.anyio
async def test_post_check_request_candidates_returns_ranked_candidates(
    client,
    seeded_page_asset,
):
    response = client.post(
        "/api/v1/check-requests:candidates",
        json={
            "system_hint": "ERP",
            "page_hint": "用户管理",
            "intent": "查询用户名 alice 是否存在",
            "slot_hints": {"field": "username", "value": "alice"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert 1 <= len(body["candidates"]) <= 3
    assert body["candidates"][0]["rank_score"] >= body["candidates"][-1]["rank_score"]
