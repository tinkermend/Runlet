import pytest
from sqlmodel import select

from app.infrastructure.db.models.jobs import QueuedJob


def test_post_auth_refresh_accepts_job(client, seeded_system, db_session):
    response = client.post(f"/api/v1/systems/{seeded_system.id}/auth:refresh")

    assert response.status_code == 202
    assert response.json() == {
        "system_id": str(seeded_system.id),
        "status": "accepted",
        "job_type": "auth_refresh",
    }

    job = db_session.exec(select(QueuedJob)).one()
    assert job.job_type == "auth_refresh"
    assert job.payload == {"system_id": str(seeded_system.id)}


def test_post_crawl_accepts_job(client, seeded_system, db_session):
    response = client.post(
        f"/api/v1/systems/{seeded_system.id}/crawl",
        json={
            "crawl_scope": "full",
            "framework_hint": "auto",
            "max_pages": 50,
        },
    )

    assert response.status_code == 202
    assert response.json() == {
        "system_id": str(seeded_system.id),
        "status": "accepted",
        "job_type": "crawl",
        "snapshot_pending": True,
    }

    job = db_session.exec(select(QueuedJob)).one()
    assert job.job_type == "crawl"
    assert job.payload == {
        "system_id": str(seeded_system.id),
        "crawl_scope": "full",
        "framework_hint": "auto",
        "max_pages": 50,
    }


def test_post_compile_assets_accepts_job(client, seeded_snapshot, db_session):
    response = client.post(
        f"/api/v1/snapshots/{seeded_snapshot.id}/compile-assets",
        json={"compile_scope": "impacted_pages_only"},
    )

    assert response.status_code == 202
    assert response.json() == {
        "snapshot_id": str(seeded_snapshot.id),
        "status": "accepted",
        "job_type": "asset_compile",
    }

    job = db_session.exec(select(QueuedJob)).one()
    assert job.job_type == "asset_compile"
    assert job.payload == {
        "snapshot_id": str(seeded_snapshot.id),
        "compile_scope": "impacted_pages_only",
    }


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/v1/systems/00000000-0000-0000-0000-000000000001/auth:refresh", None),
        (
            "/api/v1/systems/00000000-0000-0000-0000-000000000001/crawl",
            {"crawl_scope": "full", "framework_hint": "auto", "max_pages": 50},
        ),
        (
            "/api/v1/snapshots/00000000-0000-0000-0000-000000000001/compile-assets",
            {"compile_scope": "impacted_pages_only"},
        ),
    ],
)
def test_job_submission_returns_404_when_target_missing(client, db_session, path, payload):
    response = client.post(path, json=payload)

    assert response.status_code == 404
    assert db_session.exec(select(QueuedJob)).all() == []
