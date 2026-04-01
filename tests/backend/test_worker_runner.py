from datetime import timedelta
from uuid import uuid4

import pytest

from app.domains.auth_service.schemas import AuthRefreshResult
from app.domains.control_plane.job_types import AUTH_REFRESH_JOB_TYPE, ASSET_COMPILE_JOB_TYPE
from app.infrastructure.db.models.jobs import QueuedJob, utcnow
from app.jobs.auth_refresh_job import AuthRefreshJobHandler
from app.shared.enums import QueuedJobStatus
from app.workers.runner import WorkerRunner


class StubAuthService:
    def __init__(self, result: AuthRefreshResult) -> None:
        self.result = result
        self.calls = []

    async def refresh_auth_state(self, *, system_id):
        self.calls.append(system_id)
        return self.result


def _create_auth_job(db_session, *, system_id, created_at) -> QueuedJob:
    job = QueuedJob(
        job_type=AUTH_REFRESH_JOB_TYPE,
        payload={"system_id": str(system_id)},
        created_at=created_at,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


@pytest.mark.anyio
async def test_worker_runner_fetches_accepted_jobs_in_fifo_order(
    db_session,
    seeded_system,
):
    older_job = _create_auth_job(
        db_session,
        system_id=seeded_system.id,
        created_at=utcnow() - timedelta(minutes=5),
    )
    newer_job = _create_auth_job(
        db_session,
        system_id=seeded_system.id,
        created_at=utcnow() - timedelta(minutes=1),
    )
    auth_service = StubAuthService(
        AuthRefreshResult(
            system_id=seeded_system.id,
            status="success",
            auth_state_id=uuid4(),
        )
    )
    job_runner = WorkerRunner(
        session=db_session,
        handlers={
            AUTH_REFRESH_JOB_TYPE: AuthRefreshJobHandler(
                session=db_session,
                auth_service=auth_service,
            )
        },
    )

    await job_runner.run_once()

    first = db_session.get(QueuedJob, older_job.id)
    second = db_session.get(QueuedJob, newer_job.id)
    assert first is not None and second is not None
    assert first.status == QueuedJobStatus.COMPLETED.value
    assert second.status == QueuedJobStatus.ACCEPTED.value
    assert auth_service.calls == [seeded_system.id]


@pytest.mark.anyio
async def test_worker_runner_marks_unhandled_job_as_skipped_with_reason(
    db_session,
):
    job = QueuedJob(
        job_type=ASSET_COMPILE_JOB_TYPE,
        payload={"snapshot_id": str(uuid4())},
        created_at=utcnow(),
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    job_runner = WorkerRunner(session=db_session, handlers={})

    await job_runner.run_once()

    refreshed = db_session.get(QueuedJob, job.id)
    assert refreshed is not None
    assert refreshed.status == QueuedJobStatus.SKIPPED.value
    assert refreshed.failure_message == "no handler registered for job type: asset_compile"
