from __future__ import annotations

import pytest

from app.domains.control_plane.scheduler_registry import (
    build_auth_policy_job_id,
    build_crawl_policy_job_id,
    build_published_job_id,
)


def test_scheduler_registry_builds_stable_job_ids():
    assert build_published_job_id("123") == "published_job:123"
    assert build_auth_policy_job_id("sys-1") == "auth_policy:sys-1"
    assert build_crawl_policy_job_id("sys-1") == "crawl_policy:sys-1"


@pytest.mark.anyio
async def test_registry_upserts_published_job_into_apscheduler(registry, seeded_published_job):
    await registry.upsert_published_job(seeded_published_job.id)
    job = registry.scheduler.get_job(f"published_job:{seeded_published_job.id}")
    assert job is not None
