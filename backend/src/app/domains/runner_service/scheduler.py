from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session, select

from app.infrastructure.db.models.execution import ScriptRender
from app.infrastructure.db.models.jobs import JobRun, PublishedJob
from app.infrastructure.queue.dispatcher import QueueDispatcher
from app.jobs.published_job_trigger import PublishedJobTrigger
from app.shared.enums import PublishedJobState


def _validate_required_text(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("value must not be empty")
    return normalized


class PublishedJobNotFoundError(ValueError):
    pass


class InvalidPublishedJobScheduleError(ValueError):
    pass


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
    ) -> None:
        self.session = session
        self.dispatcher = dispatcher
        self.trigger = PublishedJobTrigger(session=session, dispatcher=dispatcher)

    async def create_published_job(
        self,
        *,
        payload: CreatePublishedJobRequest,
    ) -> PublishedJobCreated:
        _validate_cron_expr(payload.schedule_expr)

        script_render = await self._get(ScriptRender, payload.script_render_id)
        if script_render is None:
            raise PublishedJobNotFoundError(f"script render {payload.script_render_id} not found")

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
            raise PublishedJobNotFoundError(f"published job {published_job_id} not found")

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
            raise PublishedJobNotFoundError(f"published job {published_job_id} not found")

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
        if not _cron_matches(schedule_expr=locked_job.schedule_expr, scheduled_at=scheduled_at):
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


def _validate_cron_expr(schedule_expr: str) -> None:
    try:
        CronTrigger.from_crontab(schedule_expr, timezone="UTC")
    except ValueError as exc:
        raise InvalidPublishedJobScheduleError(f"invalid schedule expression: {schedule_expr}") from exc


def _state_value(value: PublishedJobState | str) -> str:
    return value.value if isinstance(value, PublishedJobState) else str(value)


def _minute_key(value: datetime) -> datetime:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).replace(second=0, microsecond=0)


def _cron_matches(*, schedule_expr: str, scheduled_at: datetime) -> bool:
    parts = schedule_expr.split()
    if len(parts) != 5:
        return False
    minute, hour, day_of_month, month, weekday = parts
    trigger_time = _minute_key(scheduled_at)
    minute_matches = _cron_field_matches(minute, trigger_time.minute)
    hour_matches = _cron_field_matches(hour, trigger_time.hour)
    month_matches = _cron_field_matches(month, trigger_time.month)
    day_of_month_matches = _cron_field_matches(day_of_month, trigger_time.day)
    weekday_matches = _cron_weekday_matches(weekday, _cron_weekday(trigger_time))
    day_matches = _cron_day_matches(
        day_of_month=day_of_month,
        day_of_month_matches=day_of_month_matches,
        weekday=weekday,
        weekday_matches=weekday_matches,
    )
    return minute_matches and hour_matches and month_matches and day_matches


def _cron_day_matches(
    *,
    day_of_month: str,
    day_of_month_matches: bool,
    weekday: str,
    weekday_matches: bool,
) -> bool:
    # Cron semantics: when both DOM and DOW are restricted, either may match.
    if day_of_month == "*" and weekday == "*":
        return True
    if day_of_month == "*":
        return weekday_matches
    if weekday == "*":
        return day_of_month_matches
    return day_of_month_matches or weekday_matches


def _cron_weekday(value: datetime) -> int:
    # Python weekday(): Monday=0..Sunday=6; cron: Sunday=0 (or 7), Monday=1..Saturday=6.
    return (value.weekday() + 1) % 7


def _cron_field_matches(field: str, value: int) -> bool:
    if field == "*":
        return True
    if field.startswith("*/"):
        try:
            interval = int(field[2:])
        except ValueError:
            return False
        return interval > 0 and value % interval == 0
    try:
        return int(field) == value
    except ValueError:
        return False


def _cron_weekday_matches(field: str, value: int) -> bool:
    if field == "*":
        return True
    if field.startswith("*/"):
        try:
            interval = int(field[2:])
        except ValueError:
            return False
        return interval > 0 and value % interval == 0
    try:
        expected = int(field)
    except ValueError:
        return False
    if expected == 7:
        expected = 0
    if expected < 0 or expected > 6:
        return False
    return expected == value
