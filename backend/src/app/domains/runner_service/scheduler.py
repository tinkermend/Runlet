from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable
from uuid import UUID

from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session, select

from app.infrastructure.db.models.execution import ScriptRender
from app.infrastructure.db.models.jobs import JobRun, PublishedJob
from app.infrastructure.queue.dispatcher import QueueDispatcher
from app.jobs.published_job_trigger import PublishedJobTrigger
from app.shared.enums import PublishedJobState


def utcnow() -> datetime:
    return datetime.now(UTC)


def _validate_required_text(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("value must not be empty")
    return normalized


class CreatePublishedJobRequest(BaseModel):
    script_render_id: UUID
    page_check_id: UUID
    schedule_type: str = "cron"
    schedule_expr: str
    trigger_source: str = "platform"
    enabled: bool = True

    @field_validator("schedule_type", "schedule_expr", "trigger_source", mode="before")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _validate_required_text(value)


class PublishedJobCreated(BaseModel):
    published_job_id: UUID
    page_check_id: UUID
    script_render_id: UUID
    schedule_expr: str
    state: str
    asset_version: str | None = None


class PublishedJobTriggerAccepted(BaseModel):
    published_job_id: UUID
    job_run_id: UUID
    queued_job_id: UUID
    status: str = "accepted"


class PublishedJobRunItem(BaseModel):
    id: UUID
    published_job_id: UUID
    execution_run_id: UUID | None = None
    trigger_source: str
    run_status: str
    scheduled_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failure_message: str | None = None


class PublishedJobRunsList(BaseModel):
    published_job_id: UUID
    runs: list[PublishedJobRunItem]


class PublishedJobService:
    def __init__(
        self,
        *,
        session: Session | AsyncSession,
        dispatcher: QueueDispatcher,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self.dispatcher = dispatcher
        self.now_provider = now_provider or utcnow
        self.trigger = PublishedJobTrigger(session=session, dispatcher=dispatcher)

    async def create_published_job(
        self,
        *,
        payload: CreatePublishedJobRequest,
    ) -> PublishedJobCreated:
        script_render = await self._get(ScriptRender, payload.script_render_id)
        if script_render is None:
            raise ValueError(f"script render {payload.script_render_id} not found")

        render_metadata = script_render.render_metadata or {}
        published_job = PublishedJob(
            job_key=_build_job_key(payload.page_check_id, payload.script_render_id),
            page_check_id=payload.page_check_id,
            script_render_id=payload.script_render_id,
            asset_version=_optional_text(render_metadata.get("asset_version")),
            runtime_policy=_optional_text(render_metadata.get("runtime_policy")) or payload.schedule_type,
            schedule_expr=payload.schedule_expr,
            state=PublishedJobState.ACTIVE if payload.enabled else PublishedJobState.PAUSED,
        )
        self.session.add(published_job)
        await self._commit()
        await self._refresh(published_job)

        return PublishedJobCreated(
            published_job_id=published_job.id,
            page_check_id=published_job.page_check_id,
            script_render_id=payload.script_render_id,
            schedule_expr=published_job.schedule_expr,
            state=published_job.state.value,
            asset_version=published_job.asset_version,
        )

    async def trigger_published_job(
        self,
        *,
        published_job_id: UUID,
        trigger_source: str = "manual",
    ) -> PublishedJobTriggerAccepted:
        published_job = await self._get(PublishedJob, published_job_id)
        if published_job is None:
            raise ValueError(f"published job {published_job_id} not found")

        job_run, queued_job_id = await self.trigger.trigger(
            published_job=published_job,
            trigger_source=trigger_source,
        )
        return PublishedJobTriggerAccepted(
            published_job_id=published_job.id,
            job_run_id=job_run.id,
            queued_job_id=queued_job_id,
        )

    async def list_published_job_runs(
        self,
        *,
        published_job_id: UUID,
    ) -> PublishedJobRunsList:
        published_job = await self._get(PublishedJob, published_job_id)
        if published_job is None:
            raise ValueError(f"published job {published_job_id} not found")

        statement = (
            select(JobRun)
            .where(JobRun.published_job_id == published_job_id)
            .order_by(JobRun.scheduled_at.desc(), JobRun.id.desc())
        )
        runs = await self._exec_all(statement)
        return PublishedJobRunsList(
            published_job_id=published_job.id,
            runs=[
                PublishedJobRunItem(
                    id=run.id,
                    published_job_id=run.published_job_id,
                    execution_run_id=run.execution_run_id,
                    trigger_source=run.trigger_source,
                    run_status=run.run_status,
                    scheduled_at=run.scheduled_at,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                    failure_message=run.failure_message,
                )
                for run in runs
            ],
        )

    async def trigger_scheduled_job(
        self,
        *,
        published_job_id: UUID,
        scheduled_at: datetime,
    ) -> bool:
        locked_job = await self._lock_published_job(published_job_id=published_job_id)
        if locked_job is None or _state_value(locked_job.state) != PublishedJobState.ACTIVE.value:
            return False
        if await self._already_triggered_for_minute(
            published_job_id=locked_job.id,
            scheduled_at=scheduled_at,
        ):
            return False
        await self.trigger.trigger(
            published_job=locked_job,
            trigger_source="scheduler",
            scheduled_at=scheduled_at,
        )
        return True

    async def _lock_published_job(self, *, published_job_id: UUID) -> PublishedJob | None:
        statement = select(PublishedJob).where(PublishedJob.id == published_job_id).with_for_update()
        return await self._exec_first(statement)

    async def _already_triggered_for_minute(
        self,
        *,
        published_job_id: UUID,
        scheduled_at: datetime,
    ) -> bool:
        statement = (
            select(JobRun)
            .where(JobRun.published_job_id == published_job_id)
            .order_by(JobRun.scheduled_at.desc(), JobRun.id.desc())
        )
        latest = await self._exec_first(statement)
        if latest is None:
            return False
        return _minute_key(latest.scheduled_at) == _minute_key(scheduled_at)

    async def _get(self, model, identifier):
        if isinstance(self.session, AsyncSession):
            return await self.session.get(model, identifier)
        return self.session.get(model, identifier)

    async def _exec_first(self, statement):
        if isinstance(self.session, AsyncSession):
            result = await self.session.exec(statement)
            return result.first()
        return self.session.exec(statement).first()

    async def _exec_all(self, statement):
        if isinstance(self.session, AsyncSession):
            result = await self.session.exec(statement)
            return result.all()
        return self.session.exec(statement).all()

    async def _commit(self) -> None:
        if isinstance(self.session, AsyncSession):
            await self.session.commit()
            return
        self.session.commit()

    async def _refresh(self, model) -> None:
        if isinstance(self.session, AsyncSession):
            await self.session.refresh(model)
            return
        self.session.refresh(model)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _build_job_key(page_check_id: UUID, script_render_id: UUID) -> str:
    return f"{page_check_id.hex[:12]}_{script_render_id.hex[:12]}"


def _state_value(value: PublishedJobState | str) -> str:
    return value.value if isinstance(value, PublishedJobState) else str(value)


def _minute_key(value: datetime) -> datetime:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).replace(second=0, microsecond=0)
