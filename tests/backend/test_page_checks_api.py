import pytest
from sqlmodel import select

from app.infrastructure.db.models.assets import PageCheck
from app.shared.enums import AssetStatus


@pytest.fixture
def seeded_page_asset(seeded_asset):
    return seeded_asset


@pytest.fixture
def seeded_page_check(db_session, seeded_page_asset):
    statement = select(PageCheck).where(PageCheck.page_asset_id == seeded_page_asset.id)
    return db_session.exec(statement).one()


@pytest.fixture
def seeded_non_ready_page_asset(db_session, seeded_page_asset):
    seeded_page_asset.status = AssetStatus.STALE
    db_session.add(seeded_page_asset)
    db_session.commit()
    db_session.refresh(seeded_page_asset)
    return seeded_page_asset


def test_post_page_check_run_accepts_job(client, seeded_page_check):
    response = client.post(
        f"/api/v1/page-checks/{seeded_page_check.id}:run",
        json={"strictness": "strict", "time_budget_ms": 15000, "triggered_by": "manual"},
    )

    assert response.status_code == 202
    assert response.json()["page_check_id"] == str(seeded_page_check.id)


def test_get_page_asset_checks_lists_ready_checks(client, seeded_page_asset):
    response = client.get(f"/api/v1/page-assets/{seeded_page_asset.id}/checks")

    assert response.status_code == 200
    assert response.json()["checks"][0]["status"] == "ready"


def test_get_page_asset_checks_preserves_persisted_checks_for_non_ready_asset(
    client,
    seeded_non_ready_page_asset,
):
    response = client.get(f"/api/v1/page-assets/{seeded_non_ready_page_asset.id}/checks")

    assert response.status_code == 200
    assert len(response.json()["checks"]) == 1
    assert response.json()["checks"][0]["status"] == "stale"
