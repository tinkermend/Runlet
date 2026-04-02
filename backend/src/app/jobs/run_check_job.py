from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session

from app.infrastructure.db.models.jobs import QueuedJob
from app.shared.enums import QueuedJobStatus


def utcnow() -> datetime:
    return datetime.now(UTC)


class RunCheckJobHandler:
    def __init__(self, *, session: Session | AsyncSession, runner_service) -> None:
        self.session = session
        self.runner_service = runner_service

    async def run(self, *, job_id: UUID) -> None:
        job = await self._get(QueuedJob, job_id)
        if job is None:
            raise ValueError(f"queued job {job_id} not found")

        page_check_id = job.payload.get("page_check_id")
        execution_track = str(job.payload.get("execution_track") or "").strip().lower()
        if page_check_id is None and execution_track == "realtime":
            job.status = QueuedJobStatus.SKIPPED.value
            job.started_at = job.started_at or utcnow()
            job.finished_at = utcnow()
            job.failure_message = "realtime execution track is not supported by run_check worker"
            await self._commit()
            return

        if not isinstance(page_check_id, str):
            await self._mark_failed(job, message="missing page_check_id in run_check job payload")
            return

        raw_execution_plan_id = job.payload.get("execution_plan_id")
        execution_plan_id = raw_execution_plan_id if isinstance(raw_execution_plan_id, str) else None
        raw_execution_request_id = job.payload.get("execution_request_id")
        execution_request_id = (
            raw_execution_request_id if isinstance(raw_execution_request_id, str) else None
        )

        job.status = QueuedJobStatus.RUNNING.value
        job.started_at = job.started_at or utcnow()
        await self._commit()

        try:
            result = await self.runner_service.run_page_check(
                page_check_id=UUID(page_check_id),
                execution_plan_id=UUID(execution_plan_id) if execution_plan_id else None,
            )
        except Exception as exc:
            await self._mark_failed(job, message=str(exc))
            return

        job.status = QueuedJobStatus.COMPLETED.value
        job.finished_at = utcnow()
        job.failure_message = None
        job.result_payload = {
            "page_check_id": str(result.page_check_id),
            "execution_request_id": execution_request_id,
            "execution_plan_id": execution_plan_id,
            "execution_run_id": str(result.execution_run_id),
            "status": result.status.value,
            "auth_status": result.auth_status.value,
            "artifact_ids": [str(artifact_id) for artifact_id in result.artifact_ids],
        }
        await self._commit()

    async def _mark_failed(self, job: QueuedJob, *, message: str | None) -> None:
        job.status = QueuedJobStatus.FAILED.value
        job.started_at = job.started_at or utcnow()
        job.finished_at = utcnow()
        job.failure_message = message
        await self._commit()

    async def _get(self, model, identifier):
        if isinstance(self.session, AsyncSession):
            return await self.session.get(model, identifier)
        return self.session.get(model, identifier)

    async def _commit(self) -> None:
        if isinstance(self.session, AsyncSession):
            await self.session.commit()
            return
        self.session.commit()
