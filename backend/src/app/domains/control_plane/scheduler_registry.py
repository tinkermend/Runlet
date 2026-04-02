from __future__ import annotations

from typing import Any
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


def build_auth_policy_job_id(policy_id: UUID | str) -> str:
    return f"auth_policy:{policy_id}"


def build_crawl_policy_job_id(policy_id: UUID | str) -> str:
    return f"crawl_policy:{policy_id}"


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
        session: Session | AsyncSession,
        scheduler: BaseScheduler,
        published_job_service: Any | None = None,
    ) -> None:
        self.session = session
        self.scheduler = scheduler
        self.published_job_service = published_job_service

    async def load_all_from_db(self) -> None:
        published_jobs = await self._exec_all(select(PublishedJob.id))
        auth_policies = await self._exec_all(select(SystemAuthPolicy.id))
        crawl_policies = await self._exec_all(select(SystemCrawlPolicy.id))

        for row in published_jobs:
            await self.upsert_published_job(row)
        for row in auth_policies:
            await self.upsert_auth_policy(row)
        for row in crawl_policies:
            await self.upsert_crawl_policy(row)

    async def upsert_published_job(self, published_job_id: UUID) -> None:
        job_id = build_published_job_id(published_job_id)
        published_job = await self._get(PublishedJob, published_job_id)
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
        job_id = build_auth_policy_job_id(policy_id)
        policy = await self._get(SystemAuthPolicy, policy_id)
        if policy is None:
            self.remove_job(job_id)
            return
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
        job_id = build_crawl_policy_job_id(policy_id)
        policy = await self._get(SystemCrawlPolicy, policy_id)
        if policy is None:
            self.remove_job(job_id)
            return
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

    async def _get(self, model: type, identifier: UUID):
        if isinstance(self.session, AsyncSession):
            return await self.session.get(model, identifier)
        return self.session.get(model, identifier)

    async def _exec_all(self, statement):
        if isinstance(self.session, AsyncSession):
            result = await self.session.exec(statement)
            return result.all()
        return self.session.exec(statement).all()
