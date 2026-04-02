from sqlmodel import select

from app.infrastructure.db.models.jobs import QueuedJob


def test_compile_assets_endpoint_returns_job_id(client, seeded_snapshot, db_session):
    response = client.post(
        f"/api/v1/snapshots/{seeded_snapshot.id}/compile-assets",
        json={"compile_scope": "impacted_pages_only"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body == {
        "snapshot_id": str(seeded_snapshot.id),
        "status": "accepted",
        "job_type": "asset_compile",
        "job_id": body["job_id"],
    }
    assert body["job_id"]

    job = db_session.exec(select(QueuedJob)).one()
    assert str(job.id) == body["job_id"]
    assert job.job_type == "asset_compile"
