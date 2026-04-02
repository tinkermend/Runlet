from sqlmodel import select

from app.infrastructure.db.models.runtime_policies import SystemAuthPolicy, SystemCrawlPolicy


def test_put_auth_policy_upserts_and_registers_scheduler_job(
    client,
    seeded_system,
    scheduler_runtime,
    db_session,
):
    response = client.put(
        f"/api/v1/systems/{seeded_system.id}/auth-policy",
        json={"enabled": True, "schedule_expr": "*/30 * * * *", "auth_mode": "slider_captcha"},
    )

    assert response.status_code == 200
    persisted_policy = db_session.exec(
        select(SystemAuthPolicy).where(SystemAuthPolicy.system_id == seeded_system.id)
    ).one()
    assert persisted_policy.id != seeded_system.id
    assert scheduler_runtime.scheduler.get_job(f"auth_policy:{seeded_system.id}") is not None


def test_get_auth_policy_returns_404_when_absent(client, seeded_system):
    response = client.get(f"/api/v1/systems/{seeded_system.id}/auth-policy")

    assert response.status_code == 404


def test_put_auth_policy_handles_unique_race_and_keeps_single_row(
    client,
    seeded_system,
    db_session,
    control_plane_service,
    monkeypatch,
):
    existing = SystemAuthPolicy(
        system_id=seeded_system.id,
        enabled=True,
        state="active",
        schedule_expr="*/15 * * * *",
        auth_mode="none",
    )
    db_session.add(existing)
    db_session.commit()
    db_session.refresh(existing)

    original_get = control_plane_service.repository.get_system_auth_policy
    call_count = {"value": 0}

    async def stale_get(*, system_id):
        if call_count["value"] == 0:
            call_count["value"] = 1
            return None
        return await original_get(system_id=system_id)

    monkeypatch.setattr(control_plane_service.repository, "get_system_auth_policy", stale_get)

    response = client.put(
        f"/api/v1/systems/{seeded_system.id}/auth-policy",
        json={"enabled": True, "schedule_expr": "*/30 * * * *", "auth_mode": "slider_captcha"},
    )

    assert response.status_code == 200
    rows = db_session.exec(
        select(SystemAuthPolicy).where(SystemAuthPolicy.system_id == seeded_system.id)
    ).all()
    assert len(rows) == 1
    assert rows[0].id == existing.id
    assert rows[0].schedule_expr == "*/30 * * * *"
    assert rows[0].auth_mode == "slider_captcha"


def test_put_auth_policy_returns_success_when_registry_sync_fails(
    client,
    seeded_system,
    db_session,
    control_plane_service,
    monkeypatch,
):
    async def raise_registry_failure(policy_id):
        raise RuntimeError(f"registry unavailable for {policy_id}")

    monkeypatch.setattr(
        control_plane_service.scheduler_registry,
        "upsert_auth_policy",
        raise_registry_failure,
    )

    response = client.put(
        f"/api/v1/systems/{seeded_system.id}/auth-policy",
        json={"enabled": True, "schedule_expr": "*/30 * * * *", "auth_mode": "slider_captcha"},
    )

    assert response.status_code == 200
    persisted_policy = db_session.exec(
        select(SystemAuthPolicy).where(SystemAuthPolicy.system_id == seeded_system.id)
    ).one()
    assert persisted_policy.schedule_expr == "*/30 * * * *"
    assert persisted_policy.auth_mode == "slider_captcha"


def test_put_auth_policy_rejects_invalid_auth_mode(client, seeded_system, db_session):
    response = client.put(
        f"/api/v1/systems/{seeded_system.id}/auth-policy",
        json={"enabled": True, "schedule_expr": "*/30 * * * *", "auth_mode": "invalid_mode"},
    )

    assert response.status_code == 422
    rows = db_session.exec(
        select(SystemAuthPolicy).where(SystemAuthPolicy.system_id == seeded_system.id)
    ).all()
    assert rows == []


def test_put_crawl_policy_disables_scheduler_job_when_enabled_false(
    client,
    seeded_system,
    scheduler_runtime,
    db_session,
):
    client.put(
        f"/api/v1/systems/{seeded_system.id}/crawl-policy",
        json={"enabled": True, "schedule_expr": "0 */2 * * *", "crawl_scope": "incremental"},
    )
    response = client.put(
        f"/api/v1/systems/{seeded_system.id}/crawl-policy",
        json={"enabled": False, "schedule_expr": "0 */2 * * *", "crawl_scope": "incremental"},
    )

    assert response.status_code == 200
    persisted_policy = db_session.exec(
        select(SystemCrawlPolicy).where(SystemCrawlPolicy.system_id == seeded_system.id)
    ).one()
    assert persisted_policy.id != seeded_system.id
    assert scheduler_runtime.scheduler.get_job(f"crawl_policy:{seeded_system.id}") is None


def test_get_crawl_policy_returns_saved_policy(client, seeded_system):
    put_response = client.put(
        f"/api/v1/systems/{seeded_system.id}/crawl-policy",
        json={"enabled": True, "schedule_expr": "0 */2 * * *", "crawl_scope": "incremental"},
    )
    assert put_response.status_code == 200

    get_response = client.get(f"/api/v1/systems/{seeded_system.id}/crawl-policy")

    assert get_response.status_code == 200
    assert get_response.json()["system_id"] == str(seeded_system.id)
    assert get_response.json()["crawl_scope"] == "incremental"


def test_put_crawl_policy_rejects_invalid_crawl_scope(client, seeded_system, db_session):
    response = client.put(
        f"/api/v1/systems/{seeded_system.id}/crawl-policy",
        json={"enabled": True, "schedule_expr": "0 */2 * * *", "crawl_scope": "invalid_scope"},
    )

    assert response.status_code == 422
    rows = db_session.exec(
        select(SystemCrawlPolicy).where(SystemCrawlPolicy.system_id == seeded_system.id)
    ).all()
    assert rows == []
