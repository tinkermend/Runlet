from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session

from app.infrastructure.db.models.jobs import JobRun, QueuedJob
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

        raw_published_job_id = job.payload.get("published_job_id")
        published_job_id = _parse_uuid(raw_published_job_id) if isinstance(raw_published_job_id, str) else None
        if raw_published_job_id is not None and published_job_id is None:
            await self._mark_failed(job, message="invalid published_job_id in run_check job payload")
            return

        page_check_id = job.payload.get("page_check_id")
        execution_track = str(job.payload.get("execution_track") or "").strip().lower()
        raw_execution_plan_id = job.payload.get("execution_plan_id")
        execution_plan_id = raw_execution_plan_id if isinstance(raw_execution_plan_id, str) else None
        parsed_execution_plan_id = _parse_uuid(execution_plan_id)
        if execution_plan_id is not None and parsed_execution_plan_id is None:
            await self._mark_failed(job, message="invalid execution_plan_id in run_check job payload")
            return

        if page_check_id is None and execution_track == "realtime":
            job.status = QueuedJobStatus.SKIPPED.value
            job.started_at = job.started_at or utcnow()
            job.finished_at = utcnow()
            job.failure_message = "realtime execution track is not supported by run_check worker"
            job.result_payload = self._build_result_payload(
                job=job,
                queue_status=job.status,
                execution_status="skipped",
                error_message=job.failure_message,
            )
            await self._commit()
            return

        if execution_track == "realtime_probe" and parsed_execution_plan_id is None:
            await self._mark_failed(job, message="missing execution_plan_id in run_check job payload")
            return

        if execution_track != "realtime_probe" and not isinstance(page_check_id, str):
            await self._mark_failed(job, message="missing page_check_id in run_check job payload")
            return

        raw_execution_request_id = job.payload.get("execution_request_id")
        execution_request_id = (
            raw_execution_request_id if isinstance(raw_execution_request_id, str) else None
        )
        raw_job_run_id = job.payload.get("job_run_id")
        job_run = None
        if raw_job_run_id is not None:
            job_run_id = _parse_uuid(raw_job_run_id) if isinstance(raw_job_run_id, str) else None
            if job_run_id is None:
                await self._mark_failed(job, message="invalid job_run_id in run_check job payload")
                return
            job_run = await self._get(JobRun, job_run_id)
            if job_run is None:
                await self._mark_failed(job, message=f"job run {raw_job_run_id} not found")
                return
            if published_job_id is not None and job_run.published_job_id != published_job_id:
                await self._mark_failed(
                    job,
                    message="published_job_id does not match job_run linkage",
                    job_run=job_run,
                )
                return

        job.status = QueuedJobStatus.RUNNING.value
        job.started_at = job.started_at or utcnow()
        if job_run is not None:
            job_run.run_status = QueuedJobStatus.RUNNING.value
            job_run.started_at = job_run.started_at or utcnow()
        await self._commit()

        try:
            if execution_track == "realtime_probe":
                result = await self.runner_service.run_realtime_probe(
                    execution_plan_id=parsed_execution_plan_id,
                )
            else:
                result = await self.runner_service.run_page_check(
                    page_check_id=UUID(page_check_id),
                    execution_plan_id=parsed_execution_plan_id,
                )
        except Exception as exc:
            await self._mark_failed(job, message=str(exc), job_run=job_run)
            return

        job.status = QueuedJobStatus.COMPLETED.value
        job.finished_at = utcnow()
        job.failure_message = None
        job.result_payload = self._build_result_payload(
            job=job,
            queue_status=job.status,
            execution_status=result.status.value,
            execution_request_id=execution_request_id,
            execution_plan_id=execution_plan_id,
            execution_run_id=str(result.execution_run_id),
            auth_status=result.auth_status.value,
            artifact_ids=[str(artifact_id) for artifact_id in result.artifact_ids],
        )
        if job_run is not None:
            job_run.execution_run_id = result.execution_run_id
            job_run.run_status = QueuedJobStatus.COMPLETED.value
            job_run.finished_at = utcnow()
            job_run.failure_message = None
        await self._commit()

    async def _mark_failed(
        self,
        job: QueuedJob,
        *,
        message: str | None,
        job_run: JobRun | None = None,
    ) -> None:
        job.status = QueuedJobStatus.FAILED.value
        job.started_at = job.started_at or utcnow()
        job.finished_at = utcnow()
        job.failure_message = message
        job.result_payload = self._build_result_payload(
            job=job,
            queue_status=job.status,
            execution_status="failed",
            error_message=message,
        )
        if job_run is not None:
            job_run.run_status = QueuedJobStatus.FAILED.value
            job_run.started_at = job_run.started_at or utcnow()
            job_run.finished_at = utcnow()
            job_run.failure_message = message
        await self._commit()

    def _build_result_payload(
        self,
        *,
        job: QueuedJob,
        queue_status: str,
        execution_status: str,
        execution_request_id: str | None = None,
        execution_plan_id: str | None = None,
        execution_run_id: str | None = None,
        auth_status: str | None = None,
        artifact_ids: list[str] | None = None,
        error_message: str | None = None,
    ) -> dict[str, object]:
        payload = job.payload
        return {
            "queued_job_id": str(job.id),
            "queue_status": queue_status,
            "status": execution_status,
            "page_check_id": _optional_string(payload.get("page_check_id")),
            "execution_track": _optional_string(payload.get("execution_track")),
            "execution_request_id": execution_request_id
            or _optional_string(payload.get("execution_request_id")),
            "execution_plan_id": execution_plan_id or _optional_string(payload.get("execution_plan_id")),
            "execution_run_id": execution_run_id,
            "published_job_id": _optional_string(payload.get("published_job_id")),
            "job_run_id": _optional_string(payload.get("job_run_id")),
            "script_render_id": _optional_string(payload.get("script_render_id")),
            "asset_version": _optional_string(payload.get("asset_version")),
            "runtime_policy": _optional_string(payload.get("runtime_policy")),
            "schedule_expr": _optional_string(payload.get("schedule_expr")),
            "trigger_source": _optional_string(payload.get("trigger_source")),
            "scheduled_at": _optional_string(payload.get("scheduled_at")),
            "auth_status": auth_status,
            "artifact_ids": artifact_ids or [],
            "error_message": error_message,
        }

    async def _get(self, model, identifier):
        if isinstance(self.session, AsyncSession):
            return await self.session.get(model, identifier)
        return self.session.get(model, identifier)

    async def _commit(self) -> None:
        if isinstance(self.session, AsyncSession):
            await self.session.commit()
            return
        self.session.commit()


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_uuid(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except (TypeError, ValueError):
        return None
