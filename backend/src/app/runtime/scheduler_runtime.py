from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import anyio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session

from app.domains.control_plane.job_types import AUTH_REFRESH_JOB_TYPE, CRAWL_JOB_TYPE
from app.domains.control_plane.scheduler_registry import SchedulerRegistry
from app.domains.runner_service.scheduler import PublishedJobService
from app.infrastructure.db.models.runtime_policies import SystemAuthPolicy, SystemCrawlPolicy
from app.infrastructure.queue.dispatcher import QueueDispatcher
from app.shared.enums import RuntimePolicyState, RuntimeTriggerSource


def utcnow() -> datetime:
    return datetime.now(UTC)


class SchedulerRuntime:
    def __init__(
        self,
        *,
        session: Session | AsyncSession,
        scheduler_registry: SchedulerRegistry,
        published_job_service: PublishedJobService,
        dispatcher: QueueDispatcher,
    ) -> None:
        self.session = session
        self.scheduler_registry = scheduler_registry
        self.scheduler = scheduler_registry.scheduler
        self.published_job_service = published_job_service
        self.dispatcher = dispatcher

    async def start(self) -> None:
        await self.reload_all()
        if not self.scheduler.running:
            self.scheduler.start(paused=False)
            return
        self.scheduler.resume()

    async def stop(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    async def reload_all(self) -> None:
        await self.scheduler_registry.load_all_from_db()
        self._bind_callbacks()

    async def trigger_published_job_now(
        self,
        published_job_id: UUID,
        *,
        scheduled_at: datetime | None = None,
    ) -> bool:
        run_time = _minute_key(scheduled_at or utcnow())
        await self.scheduler_registry.upsert_published_job(published_job_id)
        return await self.published_job_service.trigger_scheduled_job(
            published_job_id=published_job_id,
            scheduled_at=run_time,
        )

    async def trigger_auth_policy_now(
        self,
        policy_id: UUID,
        *,
        scheduled_at: datetime | None = None,
    ) -> bool:
        run_time = _minute_key(scheduled_at or utcnow())
        await self.scheduler_registry.upsert_auth_policy(policy_id)
        policy = await self._get(SystemAuthPolicy, policy_id)
        if policy is None:
            return False
        if not policy.enabled or _policy_state_value(policy.state) != RuntimePolicyState.ACTIVE.value:
            return False
        if _minute_key(policy.last_triggered_at) == run_time:
            return False

        await self.dispatcher.enqueue(
            job_type=AUTH_REFRESH_JOB_TYPE,
            payload={
                "system_id": str(policy.system_id),
                "policy_id": str(policy.id),
                "trigger_source": RuntimeTriggerSource.SCHEDULER.value,
                "scheduled_at": run_time.isoformat(),
            },
        )
        policy.last_triggered_at = run_time
        await self._commit()
        return True

    async def trigger_crawl_policy_now(
        self,
        policy_id: UUID,
        *,
        scheduled_at: datetime | None = None,
    ) -> bool:
        run_time = _minute_key(scheduled_at or utcnow())
        await self.scheduler_registry.upsert_crawl_policy(policy_id)
        policy = await self._get(SystemCrawlPolicy, policy_id)
        if policy is None:
            return False
        if not policy.enabled or _policy_state_value(policy.state) != RuntimePolicyState.ACTIVE.value:
            return False
        if _minute_key(policy.last_triggered_at) == run_time:
            return False

        await self.dispatcher.enqueue(
            job_type=CRAWL_JOB_TYPE,
            payload={
                "system_id": str(policy.system_id),
                "crawl_scope": policy.crawl_scope,
                "policy_id": str(policy.id),
                "trigger_source": RuntimeTriggerSource.SCHEDULER.value,
                "scheduled_at": run_time.isoformat(),
            },
        )
        policy.last_triggered_at = run_time
        await self._commit()
        return True

    def _bind_callbacks(self) -> None:
        for job in self.scheduler.get_jobs():
            if not isinstance(job.kwargs, dict):
                continue
            kind = job.kwargs.get("kind")
            entity_id = job.kwargs.get("entity_id")
            if not isinstance(kind, str) or not isinstance(entity_id, str):
                continue
            self.scheduler.add_job(
                self._dispatch_callback,
                trigger=job.trigger,
                id=job.id,
                replace_existing=True,
                kwargs={"kind": kind, "entity_id": entity_id},
            )

    def _dispatch_callback(self, *, kind: str, entity_id: str) -> None:
        anyio.run(self._dispatch_callback_async, kind=kind, entity_id=entity_id)

    async def _dispatch_callback_async(self, *, kind: str, entity_id: str) -> None:
        try:
            identifier = UUID(entity_id)
        except ValueError:
            return
        fire_time = _minute_key(utcnow())
        if kind == "published_job":
            await self.trigger_published_job_now(identifier, scheduled_at=fire_time)
            return
        if kind == "auth_policy":
            await self.trigger_auth_policy_now(identifier, scheduled_at=fire_time)
            return
        if kind == "crawl_policy":
            await self.trigger_crawl_policy_now(identifier, scheduled_at=fire_time)

    async def _get(self, model, identifier):
        if isinstance(self.session, AsyncSession):
            return await self.session.get(model, identifier)
        return self.session.get(model, identifier)

    async def _commit(self) -> None:
        if isinstance(self.session, AsyncSession):
            await self.session.commit()
            return
        self.session.commit()


def _policy_state_value(value: RuntimePolicyState | str) -> str:
    return value.value if isinstance(value, RuntimePolicyState) else str(value)


def _minute_key(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).replace(second=0, microsecond=0)
