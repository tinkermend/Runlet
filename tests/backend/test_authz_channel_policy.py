from sqlmodel import select

from app.infrastructure.db.models.jobs import QueuedJob


def _issue_skills_pat(client) -> str:
    login = client.post(
        "/api/console/auth/login",
        json={"username": "admin", "password": "admin"},
    )
    assert login.status_code == 200
    cookies = {"console_session": login.cookies["console_session"]}
    create_pat = client.post(
        "/api/v1/platform-auth/pats",
        json={"name": "skills-authz", "expires_in_days": 3},
        cookies=cookies,
    )
    assert create_pat.status_code == 201
    return create_pat.json()["token"]


def test_skills_pat_cannot_trigger_crawl(client, seeded_system, db_session):
    pat = _issue_skills_pat(client)
    response = client.post(
        f"/api/v1/systems/{seeded_system.id}/crawl",
        json={"crawl_scope": "full", "framework_hint": "auto", "max_pages": 20},
        headers={"Authorization": f"Bearer {pat}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "channel action not allowed"
    assert db_session.exec(select(QueuedJob)).all() == []
