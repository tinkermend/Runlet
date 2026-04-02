from __future__ import annotations

import pytest

from app.domains.control_plane.scheduler_registry import (
    build_auth_policy_job_id,
    build_crawl_policy_job_id,
    build_published_job_id,
)
from app.infrastructure.db.models.runtime_policies import SystemAuthPolicy, SystemCrawlPolicy
from app.shared.enums import RuntimePolicyState


def test_scheduler_registry_builds_stable_job_ids():
    assert build_published_job_id("123") == "published_job:123"
    assert build_auth_policy_job_id("sys-1") == "auth_policy:sys-1"
    assert build_crawl_policy_job_id("sys-1") == "crawl_policy:sys-1"


@pytest.mark.anyio
async def test_registry_upserts_published_job_into_apscheduler(registry, seeded_published_job):
    await registry.upsert_published_job(seeded_published_job.id)
    job = registry.scheduler.get_job(f"published_job:{seeded_published_job.id}")
    assert job is not None


@pytest.mark.anyio
async def test_registry_upserts_auth_policy_into_apscheduler(registry, seeded_system, db_session):
    policy = SystemAuthPolicy(
        system_id=seeded_system.id,
        enabled=True,
        state=RuntimePolicyState.ACTIVE.value,
        schedule_expr="*/30 * * * *",
        auth_mode="slider_captcha",
    )
    db_session.add(policy)
    db_session.commit()

    await registry.upsert_auth_policy(policy.id)

    system_scoped_job = registry.scheduler.get_job(f"auth_policy:{seeded_system.id}")
    policy_scoped_job = registry.scheduler.get_job(f"auth_policy:{policy.id}")
    assert system_scoped_job is not None
    assert policy_scoped_job is None


@pytest.mark.anyio
async def test_registry_removes_crawl_policy_job_when_policy_disabled(registry, seeded_system, db_session):
    policy = SystemCrawlPolicy(
        system_id=seeded_system.id,
        enabled=True,
        state=RuntimePolicyState.ACTIVE.value,
        schedule_expr="0 */2 * * *",
        crawl_scope="incremental",
    )
    db_session.add(policy)
    db_session.commit()

    await registry.upsert_crawl_policy(policy.id)
    assert registry.scheduler.get_job(f"crawl_policy:{seeded_system.id}") is not None
    assert registry.scheduler.get_job(f"crawl_policy:{policy.id}") is None

    policy.enabled = False
    db_session.add(policy)
    db_session.commit()

    await registry.upsert_crawl_policy(policy.id)
    assert registry.scheduler.get_job(f"crawl_policy:{seeded_system.id}") is None
