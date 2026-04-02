from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable
from uuid import UUID

import anyio
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, JobExecutionEvent
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session, select

from app.domains.control_plane.job_types import AUTH_REFRESH_JOB_TYPE, CRAWL_JOB_TYPE
from app.domains.control_plane.scheduler_registry import SchedulerRegistry
from app.domains.runner_service.scheduler import PublishedJobService
from app.infrastructure.db.models.jobs import QueuedJob
from app.infrastructure.db.models.runtime_policies import SystemAuthPolicy, SystemCrawlPolicy
from app.infrastructure.queue.dispatcher import SqlQueueDispatcher
from app.shared.enums import RuntimePolicyState, RuntimeTriggerSource


def utcnow() -> datetime:
    return datetime.now(UTC)


class SchedulerRuntime:
    def __init__(
        self,
        *,
        scheduler_registry: SchedulerRegistry,
        session_factory: Callable[[], Session | AsyncSession],
    ) -> None:
        self.scheduler_registry = scheduler_registry
        self.scheduler = scheduler_registry.scheduler
        self.session_factory = session_factory
        self._listener_registered = False

    async def start(self) -> None:
        await self.reload_all()
        self._ensure_job_listener()
        if not self.scheduler.running:
            self.scheduler.start(paused=False)
            return
        self.scheduler.resume()

    async def stop(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    async def reload_all(self) -> None:
        await self.scheduler_registry.load_all_from_db()

    async def trigger_published_job_now(
        self,
        published_job_id: UUID | str,
        *,
        scheduled_at: datetime | None = None,
    ) -> bool:
        run_time = _normalize_time(scheduled_at or utcnow())

        async def _run(session: Session | AsyncSession) -> bool:
            service = PublishedJobService(
                session=session,
                dispatcher=SqlQueueDispatcher(session),
            )
            return await service.trigger_scheduled_job(
                published_job_id=UUID(str(published_job_id)),
                scheduled_at=run_time,
            )

        return await self._with_session(_run)

    async def trigger_auth_policy_now(
        self,
        policy_id: UUID | str,
        *,
        scheduled_at: datetime | None = None,
    ) -> bool:
        run_time = _normalize_time(scheduled_at or utcnow())

        async def _run(session: Session | AsyncSession) -> bool:
            policy = await self._load_auth_policy(session=session, identifier=UUID(str(policy_id)))
            if policy is None:
                return False
            if not policy.enabled or _policy_state_value(policy.state) != RuntimePolicyState.ACTIVE.value:
                return False
            if _minute_key(policy.last_triggered_at) == _minute_key(run_time):
                return False

            queued_job_id = await SqlQueueDispatcher(session).enqueue(
                job_type=AUTH_REFRESH_JOB_TYPE,
                payload={
                    "system_id": str(policy.system_id),
                    "policy_id": str(policy.id),
                    "trigger_source": RuntimeTriggerSource.SCHEDULER.value,
                    "scheduled_at": run_time.isoformat(),
                },
            )
            queued_job = await self._get(session, QueuedJob, queued_job_id)
            if queued_job is not None:
                queued_job.policy_id = policy.id
                queued_job.trigger_source = RuntimeTriggerSource.SCHEDULER.value
                queued_job.scheduled_at = run_time
            policy.last_triggered_at = run_time
            await self._commit(session)
            return True

        return await self._with_session(_run)

    async def trigger_crawl_policy_now(
        self,
        policy_id: UUID | str,
        *,
        scheduled_at: datetime | None = None,
    ) -> bool:
        run_time = _normalize_time(scheduled_at or utcnow())

        async def _run(session: Session | AsyncSession) -> bool:
            policy = await self._load_crawl_policy(session=session, identifier=UUID(str(policy_id)))
            if policy is None:
                return False
            if not policy.enabled or _policy_state_value(policy.state) != RuntimePolicyState.ACTIVE.value:
                return False
            if _minute_key(policy.last_triggered_at) == _minute_key(run_time):
                return False

            queued_job_id = await SqlQueueDispatcher(session).enqueue(
                job_type=CRAWL_JOB_TYPE,
                payload={
                    "system_id": str(policy.system_id),
                    "crawl_scope": policy.crawl_scope,
                    "policy_id": str(policy.id),
                    "trigger_source": RuntimeTriggerSource.SCHEDULER.value,
                    "scheduled_at": run_time.isoformat(),
                },
            )
            queued_job = await self._get(session, QueuedJob, queued_job_id)
            if queued_job is not None:
                queued_job.policy_id = policy.id
                queued_job.trigger_source = RuntimeTriggerSource.SCHEDULER.value
                queued_job.scheduled_at = run_time
            policy.last_triggered_at = run_time
            await self._commit(session)
            return True

        return await self._with_session(_run)

    def _ensure_job_listener(self) -> None:
        if self._listener_registered:
            return
        self.scheduler.add_listener(
            self._on_scheduler_job_event,
            EVENT_JOB_EXECUTED | EVENT_JOB_ERROR,
        )
        self._listener_registered = True

    def _on_scheduler_job_event(self, event: JobExecutionEvent) -> None:
        resolved = self._resolve_callback_target(job_id=event.job_id)
        if resolved is None:
            return
        kind, entity_id = resolved
        self._dispatch_callback(
            kind=kind,
            entity_id=entity_id,
            scheduled_at=event.scheduled_run_time,
        )

    def _resolve_callback_target(self, *, job_id: str) -> tuple[str, str] | None:
        job = self.scheduler.get_job(job_id)
        if job is not None and isinstance(job.kwargs, dict):
            kind = job.kwargs.get("kind")
            entity_id = job.kwargs.get("entity_id")
            if isinstance(kind, str) and isinstance(entity_id, str):
                return kind, entity_id

        if ":" not in job_id:
            return None
        kind_prefix, entity_id = job_id.split(":", 1)
        kind_map = {
            "published_job": "published_job",
            "auth_policy": "auth_policy",
            "crawl_policy": "crawl_policy",
        }
        kind = kind_map.get(kind_prefix)
        if kind is None:
            return None
        return kind, entity_id

    def _dispatch_callback(
        self,
        *,
        kind: str,
        entity_id: str,
        scheduled_at: datetime | None,
    ) -> None:
        fire_time = _normalize_time(scheduled_at or utcnow())
        anyio.run(self._dispatch_callback_async, kind, entity_id, fire_time)

    async def _dispatch_callback_async(
        self,
        kind: str,
        entity_id: str,
        fire_time: datetime,
    ) -> None:
        if kind == "published_job":
            await self.trigger_published_job_now(entity_id, scheduled_at=fire_time)
            return
        if kind == "auth_policy":
            await self.trigger_auth_policy_now(entity_id, scheduled_at=fire_time)
            return
        if kind == "crawl_policy":
            await self.trigger_crawl_policy_now(entity_id, scheduled_at=fire_time)

    async def _load_auth_policy(
        self,
        *,
        session: Session | AsyncSession,
        identifier: UUID,
    ) -> SystemAuthPolicy | None:
        policy = await self._get(session, SystemAuthPolicy, identifier)
        if policy is not None:
            return policy
        statement = select(SystemAuthPolicy).where(SystemAuthPolicy.system_id == identifier)
        return await self._exec_first(session, statement)

    async def _load_crawl_policy(
        self,
        *,
        session: Session | AsyncSession,
        identifier: UUID,
    ) -> SystemCrawlPolicy | None:
        policy = await self._get(session, SystemCrawlPolicy, identifier)
        if policy is not None:
            return policy
        statement = select(SystemCrawlPolicy).where(SystemCrawlPolicy.system_id == identifier)
        return await self._exec_first(session, statement)

    async def _with_session(self, func):
        session = self.session_factory()
        try:
            return await func(session)
        finally:
            await self._close_session(session)

    async def _get(self, session: Session | AsyncSession, model, identifier):
        if isinstance(session, AsyncSession):
            return await session.get(model, identifier)
        return session.get(model, identifier)

    async def _exec_first(self, session: Session | AsyncSession, statement):
        if isinstance(session, AsyncSession):
            result = await session.exec(statement)
            return result.first()
        return session.exec(statement).first()

    async def _commit(self, session: Session | AsyncSession) -> None:
        if isinstance(session, AsyncSession):
            await session.commit()
            return
        session.commit()

    async def _close_session(self, session: Session | AsyncSession) -> None:
        if isinstance(session, AsyncSession):
            await session.close()
            return
        session.close()


def _policy_state_value(value: RuntimePolicyState | str) -> str:
    return value.value if isinstance(value, RuntimePolicyState) else str(value)


def _normalize_time(value: datetime) -> datetime:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC)


def _minute_key(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    return _normalize_time(value).replace(second=0, microsecond=0)
