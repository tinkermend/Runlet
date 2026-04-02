from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session, select

from app.infrastructure.db.models.jobs import QueuedJob
from app.infrastructure.db.models.runtime_policies import SystemAuthPolicy
from app.shared.enums import QueuedJobStatus


def utcnow() -> datetime:
    return datetime.now(UTC)


class AuthRefreshJobHandler:
    def __init__(self, *, session: Session | AsyncSession, auth_service) -> None:
        self.session = session
        self.auth_service = auth_service

    async def run(self, *, job_id: UUID) -> None:
        job = await self._get(QueuedJob, job_id)
        if job is None:
            raise ValueError(f"queued job {job_id} not found")

        self._apply_queue_audit_fields(job)
        policy = await self._resolve_policy(job)
        system_id = job.payload.get("system_id")
        if not isinstance(system_id, str):
            await self._mark_failed(
                job,
                message="missing system_id in auth refresh job payload",
                policy=policy,
            )
            return

        job.status = QueuedJobStatus.RUNNING.value
        job.started_at = job.started_at or utcnow()
        await self._commit()

        try:
            result = await self.auth_service.refresh_auth_state(system_id=UUID(system_id))
        except Exception as exc:
            await self._mark_failed(job, message=str(exc), policy=policy)
            return

        if result.status == "success":
            job.status = QueuedJobStatus.COMPLETED.value
            job.failure_message = None
            if policy is not None:
                policy.last_succeeded_at = utcnow()
                policy.last_failure_message = None
        elif result.status == "retryable_failed":
            job.status = QueuedJobStatus.RETRYABLE_FAILED.value
            job.failure_message = result.message
            if policy is not None:
                policy.last_failed_at = utcnow()
                policy.last_failure_message = result.message
        else:
            job.status = QueuedJobStatus.FAILED.value
            job.failure_message = result.message
            if policy is not None:
                policy.last_failed_at = utcnow()
                policy.last_failure_message = result.message

        job.finished_at = utcnow()
        await self._commit()

    async def _mark_failed(
        self,
        job: QueuedJob,
        *,
        message: str | None,
        policy: SystemAuthPolicy | None = None,
    ) -> None:
        job.status = QueuedJobStatus.FAILED.value
        job.started_at = job.started_at or utcnow()
        job.finished_at = utcnow()
        job.failure_message = message
        if policy is not None:
            policy.last_failed_at = utcnow()
            policy.last_failure_message = message
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

    async def _resolve_policy(self, job: QueuedJob) -> SystemAuthPolicy | None:
        policy_identifier = _parse_uuid(job.payload.get("policy_id"))
        if policy_identifier is not None:
            policy = await self._get(SystemAuthPolicy, policy_identifier)
            if policy is not None:
                return policy
            policy = await self._get_policy_by_system_id(system_id=policy_identifier)
            if policy is not None:
                return policy

        system_identifier = _parse_uuid(job.payload.get("system_id"))
        if system_identifier is None:
            return None
        return await self._get_policy_by_system_id(system_id=system_identifier)

    async def _get_policy_by_system_id(self, *, system_id: UUID) -> SystemAuthPolicy | None:
        statement = select(SystemAuthPolicy).where(SystemAuthPolicy.system_id == system_id)
        if isinstance(self.session, AsyncSession):
            result = await self.session.exec(statement)
            return result.first()
        return self.session.exec(statement).first()

    def _apply_queue_audit_fields(self, job: QueuedJob) -> None:
        policy_id = _parse_uuid(job.payload.get("policy_id"))
        if policy_id is not None:
            job.policy_id = policy_id

        trigger_source = job.payload.get("trigger_source")
        if isinstance(trigger_source, str) and trigger_source.strip():
            job.trigger_source = trigger_source.strip()

        scheduled_at = _parse_datetime(job.payload.get("scheduled_at"))
        if scheduled_at is not None:
            job.scheduled_at = scheduled_at


def _parse_uuid(value: object) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
