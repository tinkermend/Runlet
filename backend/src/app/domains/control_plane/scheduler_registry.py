from __future__ import annotations

import inspect
from collections.abc import Callable
from uuid import UUID

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session, select

from app.infrastructure.db.models.jobs import PublishedJob
from app.infrastructure.db.models.runtime_policies import SystemAuthPolicy, SystemCrawlPolicy
from app.shared.enums import PublishedJobState, RuntimePolicyState


def build_published_job_id(published_job_id: UUID | str) -> str:
    return f"published_job:{published_job_id}"


def build_auth_policy_job_id(system_id: UUID | str) -> str:
    return f"auth_policy:{system_id}"


def build_crawl_policy_job_id(system_id: UUID | str) -> str:
    return f"crawl_policy:{system_id}"


def _state_value(value: PublishedJobState | str) -> str:
    return value.value if isinstance(value, PublishedJobState) else str(value)


def _policy_state_value(value: RuntimePolicyState | str) -> str:
    return value.value if isinstance(value, RuntimePolicyState) else str(value)


def _registry_noop(*, kind: str, entity_id: str) -> None:
    # Registry-only mode: APScheduler holds trigger metadata, execution stays on control plane.
    _ = (kind, entity_id)


class SchedulerRegistry:
    def __init__(
        self,
        *,
        session: Session | AsyncSession | None = None,
        session_factory: Callable[[], Session | AsyncSession] | None = None,
        scheduler: BaseScheduler,
    ) -> None:
        if session is None and session_factory is None:
            raise ValueError("session or session_factory is required")
        self.session = session
        self.session_factory = session_factory
        self.scheduler = scheduler

    async def load_all_from_db(self) -> None:
        async def _run(session: Session | AsyncSession) -> None:
            published_jobs = await self._exec_all(session, select(PublishedJob.id))
            auth_policies = await self._exec_all(session, select(SystemAuthPolicy.id))
            crawl_policies = await self._exec_all(session, select(SystemCrawlPolicy.id))

            for row in published_jobs:
                await self._upsert_published_job(session, row)
            for row in auth_policies:
                await self._upsert_auth_policy(session, row)
            for row in crawl_policies:
                await self._upsert_crawl_policy(session, row)

        await self._with_session(_run)

    async def upsert_published_job(self, published_job_id: UUID) -> None:
        await self._with_session(lambda session: self._upsert_published_job(session, published_job_id))

    async def _upsert_published_job(
        self,
        session: Session | AsyncSession,
        published_job_id: UUID,
    ) -> None:
        job_id = build_published_job_id(published_job_id)
        published_job = await self._get(session, PublishedJob, published_job_id)
        if published_job is None:
            self.remove_job(job_id)
            return
        if _state_value(published_job.state) != PublishedJobState.ACTIVE.value:
            self.remove_job(job_id)
            return

        self._upsert_job(
            job_id=job_id,
            schedule_expr=published_job.schedule_expr,
            timezone=published_job.timezone,
            kind="published_job",
            entity_id=str(published_job.id),
        )

    async def upsert_auth_policy(self, policy_id: UUID) -> None:
        await self._with_session(lambda session: self._upsert_auth_policy(session, policy_id))

    async def _upsert_auth_policy(
        self,
        session: Session | AsyncSession,
        policy_id: UUID,
    ) -> None:
        policy = await self._get(session, SystemAuthPolicy, policy_id)
        if policy is None:
            return
        job_id = build_auth_policy_job_id(policy.system_id)
        if not policy.enabled or _policy_state_value(policy.state) != RuntimePolicyState.ACTIVE.value:
            self.remove_job(job_id)
            return

        self._upsert_job(
            job_id=job_id,
            schedule_expr=policy.schedule_expr,
            timezone="UTC",
            kind="auth_policy",
            entity_id=str(policy.id),
        )

    async def upsert_crawl_policy(self, policy_id: UUID) -> None:
        await self._with_session(lambda session: self._upsert_crawl_policy(session, policy_id))

    async def _upsert_crawl_policy(
        self,
        session: Session | AsyncSession,
        policy_id: UUID,
    ) -> None:
        policy = await self._get(session, SystemCrawlPolicy, policy_id)
        if policy is None:
            return
        job_id = build_crawl_policy_job_id(policy.system_id)
        if not policy.enabled or _policy_state_value(policy.state) != RuntimePolicyState.ACTIVE.value:
            self.remove_job(job_id)
            return

        self._upsert_job(
            job_id=job_id,
            schedule_expr=policy.schedule_expr,
            timezone="UTC",
            kind="crawl_policy",
            entity_id=str(policy.id),
        )

    def remove_job(self, job_id: str) -> None:
        try:
            self.scheduler.remove_job(job_id)
        except JobLookupError:
            return

    async def _with_session(self, operation):
        if self.session is not None:
            return await operation(self.session)

        assert self.session_factory is not None
        session = self.session_factory()
        try:
            return await operation(session)
        finally:
            closer = session.close()
            if inspect.isawaitable(closer):
                await closer

    def _upsert_job(
        self,
        *,
        job_id: str,
        schedule_expr: str,
        timezone: str,
        kind: str,
        entity_id: str,
    ) -> None:
        trigger = CronTrigger.from_crontab(schedule_expr, timezone=timezone)
        self.scheduler.add_job(
            _registry_noop,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
            kwargs={"kind": kind, "entity_id": entity_id},
        )

    async def _get(self, session: Session | AsyncSession, model: type, identifier: UUID):
        if isinstance(session, AsyncSession):
            return await session.get(model, identifier)
        return session.get(model, identifier)

    async def _exec_all(self, session: Session | AsyncSession, statement):
        if isinstance(session, AsyncSession):
            result = await session.exec(statement)
            return result.all()
        return session.exec(statement).all()
