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
