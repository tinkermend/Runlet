from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session, select

from app.domains.control_plane.job_types import ASSET_COMPILE_JOB_TYPE
from app.infrastructure.db.models.jobs import QueuedJob
from app.infrastructure.db.models.runtime_policies import SystemCrawlPolicy
from app.shared.enums import QueuedJobStatus


def utcnow() -> datetime:
    return datetime.now(UTC)


class CrawlJobHandler:
    def __init__(self, *, session: Session | AsyncSession, crawler_service) -> None:
        self.session = session
        self.crawler_service = crawler_service

    async def run(self, *, job_id: UUID) -> None:
        job = await self._get(QueuedJob, job_id)
        if job is None:
            raise ValueError(f"queued job {job_id} not found")

        self._apply_queue_audit_fields(job)
        policy = await self._resolve_policy(job)
        system_id = job.payload.get("system_id")
        crawl_scope = job.payload.get("crawl_scope", "full")
        if not isinstance(system_id, str):
            await self._mark_failed(
                job,
                message="missing system_id in crawl job payload",
                policy=policy,
            )
            return
        if not isinstance(crawl_scope, str) or not crawl_scope.strip():
            await self._mark_failed(
                job,
                message="missing crawl_scope in crawl job payload",
                policy=policy,
            )
            return

        job.status = QueuedJobStatus.RUNNING.value
        job.started_at = job.started_at or utcnow()
        await self._commit()

        try:
            result = await self.crawler_service.run_crawl(
                system_id=UUID(system_id),
                crawl_scope=crawl_scope,
            )
        except Exception as exc:
            await self._mark_failed(job, message=str(exc), policy=policy)
            return

        if result.status != "success" or result.snapshot_id is None:
            await self._mark_failed(
                job,
                message=result.message or result.status,
                policy=policy,
            )
            return

        compile_job = QueuedJob(
            job_type=ASSET_COMPILE_JOB_TYPE,
            payload={
                "snapshot_id": str(result.snapshot_id),
                "compile_scope": "impacted_pages_only",
            },
        )
        self.session.add(compile_job)
        job.status = QueuedJobStatus.COMPLETED.value
        job.failure_message = None
        job.finished_at = utcnow()
        job.result_payload = {
            "status": "success",
            "snapshot_id": str(result.snapshot_id),
        }
        if policy is not None:
            policy.last_succeeded_at = utcnow()
            policy.last_failure_message = None
        await self._commit()

    async def _mark_failed(
        self,
        job: QueuedJob,
        *,
        message: str | None,
        policy: SystemCrawlPolicy | None = None,
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

    async def _resolve_policy(self, job: QueuedJob) -> SystemCrawlPolicy | None:
        policy_identifier = _parse_uuid(job.payload.get("policy_id"))
        if policy_identifier is not None:
            policy = await self._get(SystemCrawlPolicy, policy_identifier)
            if policy is not None:
                return policy
            policy = await self._get_policy_by_system_id(system_id=policy_identifier)
            if policy is not None:
                return policy

        system_identifier = _parse_uuid(job.payload.get("system_id"))
        if system_identifier is None:
            return None
        return await self._get_policy_by_system_id(system_id=system_identifier)

    async def _get_policy_by_system_id(self, *, system_id: UUID) -> SystemCrawlPolicy | None:
        statement = select(SystemCrawlPolicy).where(SystemCrawlPolicy.system_id == system_id)
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
