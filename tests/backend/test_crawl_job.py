from uuid import uuid4

import pytest
from sqlmodel import select

from app.domains.control_plane.job_types import ASSET_COMPILE_JOB_TYPE, CRAWL_JOB_TYPE
from app.domains.crawler_service.schemas import CrawlRunResult
from app.infrastructure.db.models.crawl import CrawlSnapshot
from app.infrastructure.db.models.jobs import QueuedJob
from app.infrastructure.db.models.runtime_policies import SystemCrawlPolicy
from app.jobs.crawl_job import CrawlJobHandler
from app.workers.runner import WorkerRunner


class StubCrawlerService:
    def __init__(self, result: CrawlRunResult) -> None:
        self.result = result
        self.calls = []
        self.auto_commit_values = []

    async def run_crawl(self, *, system_id, crawl_scope: str, auto_commit: bool = True) -> CrawlRunResult:
        self.calls.append({"system_id": system_id, "crawl_scope": crawl_scope})
        self.auto_commit_values.append(auto_commit)
        return self.result


def _create_crawl_job(db_session, *, system_id, crawl_scope="full", policy_id=None) -> QueuedJob:
    payload = {"system_id": str(system_id), "crawl_scope": crawl_scope}
    if policy_id is not None:
        payload["policy_id"] = str(policy_id)

    job = QueuedJob(
        job_type=CRAWL_JOB_TYPE,
        payload=payload,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _create_crawl_policy(db_session, *, system_id, crawl_scope="full") -> SystemCrawlPolicy:
    policy = SystemCrawlPolicy(
        system_id=system_id,
        enabled=True,
        state="active",
        schedule_expr="*/15 * * * *",
        crawl_scope=crawl_scope,
    )
    db_session.add(policy)
    db_session.commit()
    db_session.refresh(policy)
    return policy


def _create_draft_snapshot(
    db_session,
    *,
    system_id,
    quality_score: float = 0.95,
    degraded: bool = False,
) -> CrawlSnapshot:
    snapshot = CrawlSnapshot(
        system_id=system_id,
        crawl_type="full",
        framework_detected="react",
        quality_score=quality_score,
        degraded=degraded,
        state="draft",
    )
    db_session.add(snapshot)
    db_session.commit()
    db_session.refresh(snapshot)
    return snapshot


@pytest.mark.anyio
async def test_crawl_job_persists_snapshot_id_and_enqueues_compile(
    db_session,
    seeded_system,
):
    policy = _create_crawl_policy(db_session, system_id=seeded_system.id)
    queued_crawl_job = _create_crawl_job(
        db_session,
        system_id=seeded_system.id,
        policy_id=policy.id,
    )
    crawler_service = StubCrawlerService(
        CrawlRunResult(
            system_id=seeded_system.id,
            status="success",
            snapshot_id=uuid4(),
            pages_saved=1,
        )
    )
    job_runner = WorkerRunner(
        session=db_session,
        handlers={
            CRAWL_JOB_TYPE: CrawlJobHandler(
                session=db_session,
                crawler_service=crawler_service,
            )
        },
    )

    await job_runner.run_once()

    refreshed_job = db_session.get(QueuedJob, queued_crawl_job.id)
    compile_jobs = db_session.exec(
        select(QueuedJob).where(QueuedJob.job_type == ASSET_COMPILE_JOB_TYPE)
    ).all()

    assert refreshed_job is not None
    assert refreshed_job.status == "completed"
    assert refreshed_job.finished_at is not None
    assert refreshed_job.result_payload == {
        "status": "success",
        "snapshot_id": str(crawler_service.result.snapshot_id),
    }
    assert crawler_service.auto_commit_values == [False]
    assert len(compile_jobs) == 1
    assert compile_jobs[0].payload["snapshot_id"] == str(crawler_service.result.snapshot_id)
    assert compile_jobs[0].payload["compile_scope"] == "impacted_pages_only"

    refreshed_policy = db_session.get(SystemCrawlPolicy, policy.id)
    assert refreshed_policy is not None
    assert refreshed_policy.last_succeeded_at is not None
    assert refreshed_policy.last_failed_at is None
    assert refreshed_policy.last_failure_message is None


@pytest.mark.anyio
async def test_crawl_job_marks_failure_without_compile_handoff_when_crawl_fails(
    db_session,
    seeded_system,
):
    policy = _create_crawl_policy(db_session, system_id=seeded_system.id)
    queued_crawl_job = _create_crawl_job(
        db_session,
        system_id=seeded_system.id,
        policy_id=seeded_system.id,
    )
    crawler_service = StubCrawlerService(
        CrawlRunResult(
            system_id=seeded_system.id,
            status="auth_required",
            message="auth required",
        )
    )
    job_runner = WorkerRunner(
        session=db_session,
        handlers={
            CRAWL_JOB_TYPE: CrawlJobHandler(
                session=db_session,
                crawler_service=crawler_service,
            )
        },
    )

    await job_runner.run_once()

    refreshed_job = db_session.get(QueuedJob, queued_crawl_job.id)
    compile_jobs = db_session.exec(
        select(QueuedJob).where(QueuedJob.job_type == ASSET_COMPILE_JOB_TYPE)
    ).all()

    assert refreshed_job is not None
    assert refreshed_job.status == "failed"
    assert refreshed_job.failure_message == "auth required"
    assert compile_jobs == []

    refreshed_policy = db_session.get(SystemCrawlPolicy, policy.id)
    assert refreshed_policy is not None
    assert refreshed_policy.last_succeeded_at is None
    assert refreshed_policy.last_failed_at is not None
    assert refreshed_policy.last_failure_message == "auth required"


@pytest.mark.anyio
async def test_crawl_job_discards_superseded_uncompiled_drafts_before_compile_handoff(
    db_session,
    seeded_system,
):
    policy = _create_crawl_policy(db_session, system_id=seeded_system.id)
    queued_crawl_job = _create_crawl_job(
        db_session,
        system_id=seeded_system.id,
        policy_id=policy.id,
    )
    older_draft = _create_draft_snapshot(db_session, system_id=seeded_system.id)
    latest_draft = _create_draft_snapshot(db_session, system_id=seeded_system.id)
    crawler_service = StubCrawlerService(
        CrawlRunResult(
            system_id=seeded_system.id,
            status="success",
            snapshot_id=latest_draft.id,
            pages_saved=1,
        )
    )
    job_runner = WorkerRunner(
        session=db_session,
        handlers={
            CRAWL_JOB_TYPE: CrawlJobHandler(
                session=db_session,
                crawler_service=crawler_service,
            )
        },
    )

    await job_runner.run_once()

    refreshed_crawl_job = db_session.get(QueuedJob, queued_crawl_job.id)
    refreshed_older = db_session.get(CrawlSnapshot, older_draft.id)
    refreshed_latest = db_session.get(CrawlSnapshot, latest_draft.id)
    compile_jobs = db_session.exec(
        select(QueuedJob).where(QueuedJob.job_type == ASSET_COMPILE_JOB_TYPE)
    ).all()

    assert refreshed_crawl_job is not None
    assert refreshed_crawl_job.status == "completed"
    assert refreshed_older is not None
    assert refreshed_older.state == "discarded"
    assert refreshed_older.discarded_at is not None
    assert refreshed_older.failure_reason == "superseded_by_newer_draft"
    assert refreshed_latest is not None
    assert refreshed_latest.state == "draft"
    assert len(compile_jobs) == 1
    assert compile_jobs[0].payload["snapshot_id"] == str(latest_draft.id)
