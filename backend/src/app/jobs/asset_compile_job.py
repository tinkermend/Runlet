from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session

from app.infrastructure.db.models.jobs import QueuedJob
from app.shared.enums import AssetStatus, QueuedJobStatus


def utcnow() -> datetime:
    return datetime.now(UTC)


class AssetCompileJobHandler:
    def __init__(self, *, session: Session | AsyncSession, asset_compiler_service) -> None:
        self.session = session
        self.asset_compiler_service = asset_compiler_service

    async def run(self, *, job_id: UUID) -> None:
        job = await self._get(QueuedJob, job_id)
        if job is None:
            raise ValueError(f"queued job {job_id} not found")

        snapshot_id = job.payload.get("snapshot_id")
        if not isinstance(snapshot_id, str):
            await self._mark_failed(job, message="missing snapshot_id in asset compile job payload")
            return

        job.status = QueuedJobStatus.RUNNING.value
        job.started_at = job.started_at or utcnow()
        await self._commit()

        try:
            result = await self.asset_compiler_service.compile_snapshot(snapshot_id=UUID(snapshot_id))
        except Exception as exc:
            await self._mark_failed(job, message=str(exc))
            return

        job.status = QueuedJobStatus.COMPLETED.value
        job.finished_at = utcnow()
        job.failure_message = None
        job.result_payload = _serialize_compile_result(result)
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


def _serialize_compile_result(result) -> dict[str, object]:
    payload = asdict(result)
    payload["snapshot_id"] = str(payload["snapshot_id"])
    payload["asset_ids"] = [str(asset_id) for asset_id in payload["asset_ids"]]
    payload["check_ids"] = [str(check_id) for check_id in payload["check_ids"]]
    payload["alias_ids_to_disable"] = [str(alias_id) for alias_id in payload["alias_ids_to_disable"]]
    payload["published_job_ids_to_pause"] = [
        str(job_id) for job_id in payload["published_job_ids_to_pause"]
    ]
    drift_state = payload.get("drift_state")
    if isinstance(drift_state, AssetStatus):
        payload["drift_state"] = drift_state.value
    return payload
