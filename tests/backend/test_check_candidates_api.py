import pytest
from sqlalchemy.dialects import postgresql

from app.domains.control_plane.repository import SqlControlPlaneRepository


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


@pytest.mark.anyio
async def test_list_check_candidates_groups_asset_version_for_postgres(
    db_session,
    seeded_page_asset,
):
    repository = SqlControlPlaneRepository(db_session)
    captured = {}

    async def fake_exec_all(statement):
        captured["statement"] = statement
        return []

    repository._exec_all = fake_exec_all  # type: ignore[method-assign]

    await repository.list_check_candidates(system_hint="ERP", page_hint="用户管理")

    compiled = str(
        captured["statement"].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "ORDER BY alias_confidence DESC, page_assets.asset_version DESC, page_checks.id" in compiled
    assert "GROUP BY" in compiled
    assert "page_assets.asset_version" in compiled.split("GROUP BY", 1)[1].split("ORDER BY", 1)[0]
