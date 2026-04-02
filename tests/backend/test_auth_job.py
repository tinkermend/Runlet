from uuid import uuid4

import pytest

from app.domains.auth_service.schemas import AuthRefreshResult
from app.domains.control_plane.job_types import AUTH_REFRESH_JOB_TYPE
from app.infrastructure.db.models.jobs import QueuedJob, utcnow
from app.infrastructure.db.models.runtime_policies import SystemAuthPolicy
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


def _create_auth_job(db_session, *, system_id, policy_id=None, created_at=None) -> QueuedJob:
    payload = {"system_id": str(system_id)}
    if policy_id is not None:
        payload["policy_id"] = str(policy_id)

    job = QueuedJob(
        job_type=AUTH_REFRESH_JOB_TYPE,
        payload=payload,
        created_at=created_at or utcnow(),
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _create_auth_policy(db_session, *, system_id) -> SystemAuthPolicy:
    policy = SystemAuthPolicy(
        system_id=system_id,
        enabled=True,
        state="active",
        schedule_expr="*/5 * * * *",
        auth_mode="storage_state",
    )
    db_session.add(policy)
    db_session.commit()
    db_session.refresh(policy)
    return policy


@pytest.mark.anyio
async def test_auth_refresh_job_marks_queue_item_completed(
    db_session,
    seeded_system,
):
    policy = _create_auth_policy(db_session, system_id=seeded_system.id)
    queued_auth_job = _create_auth_job(
        db_session,
        system_id=seeded_system.id,
        policy_id=policy.id,
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

    refreshed = db_session.get(QueuedJob, queued_auth_job.id)
    assert refreshed is not None
    assert refreshed.status == QueuedJobStatus.COMPLETED.value
    assert refreshed.started_at is not None
    assert refreshed.finished_at is not None
    assert refreshed.failure_message is None
    assert auth_service.calls == [seeded_system.id]

    refreshed_policy = db_session.get(SystemAuthPolicy, policy.id)
    assert refreshed_policy is not None
    assert refreshed_policy.last_succeeded_at is not None
    assert refreshed_policy.last_failed_at is None
    assert refreshed_policy.last_failure_message is None


@pytest.mark.anyio
async def test_auth_refresh_job_marks_queue_item_failed_when_refresh_fails(
    db_session,
    seeded_system,
):
    policy = _create_auth_policy(db_session, system_id=seeded_system.id)
    queued_auth_job = _create_auth_job(
        db_session,
        system_id=seeded_system.id,
        policy_id=seeded_system.id,
    )
    auth_service = StubAuthService(
        AuthRefreshResult(
            system_id=seeded_system.id,
            status="failed",
            message="login failed",
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

    refreshed = db_session.get(QueuedJob, queued_auth_job.id)
    assert refreshed is not None
    assert refreshed.status == QueuedJobStatus.FAILED.value
    assert refreshed.failure_message == "login failed"
    assert refreshed.started_at is not None
    assert refreshed.finished_at is not None

    refreshed_policy = db_session.get(SystemAuthPolicy, policy.id)
    assert refreshed_policy is not None
    assert refreshed_policy.last_succeeded_at is None
    assert refreshed_policy.last_failed_at is not None
    assert refreshed_policy.last_failure_message == "login failed"
