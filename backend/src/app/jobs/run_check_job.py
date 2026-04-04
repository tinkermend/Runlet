from __future__ import annotations

import anyio
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session

from app.domains.runner_service.service import ASSET_RETIRED_FAILURE_MESSAGE, ExecutionBlockedError
from app.infrastructure.db.models.assets import PageAsset, PageCheck
from app.infrastructure.db.models.execution import ExecutionRequest
from app.infrastructure.db.models.jobs import JobRun, PublishedJob, QueuedJob
from app.jobs.run_check_retry import build_attempt_entry, compute_backoff_ms, is_retryable_failure
from app.shared.enums import AssetLifecycleStatus, PublishedJobState, QueuedJobStatus

_UNSET = object()
_PRECOMPILED_MAX_ATTEMPTS = 3
_PRECOMPILED_BASE_BACKOFF_MS = 100
_PRECOMPILED_JITTER_MS = 0


def utcnow() -> datetime:
    return datetime.now(UTC)


class PrecompiledRetryTerminalError(RuntimeError):
    def __init__(self, *, message: str, retry_payload: dict[str, object]) -> None:
        super().__init__(message)
        self.retry_payload = retry_payload


class PrecompiledRetryBlockedError(ExecutionBlockedError):
    def __init__(self, *, message: str, retry_payload: dict[str, object]) -> None:
        super().__init__(reason=message)
        self.retry_payload = retry_payload


class RunCheckJobHandler:
    def __init__(
        self,
        *,
        session: Session | AsyncSession,
        runner_service,
        control_plane_service=None,
    ) -> None:
        self.session = session
        self.runner_service = runner_service
        self.control_plane_service = control_plane_service

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

        raw_execution_plan_id = job.payload.get("execution_plan_id")
        execution_plan_id = raw_execution_plan_id if isinstance(raw_execution_plan_id, str) else None
        parsed_execution_plan_id = _parse_uuid(execution_plan_id)
        if execution_plan_id is not None and parsed_execution_plan_id is None:
            await self._mark_failed(job, message="invalid execution_plan_id in run_check job payload")
            return

        if execution_track == "realtime_probe" and parsed_execution_plan_id is None:
            await self._mark_failed(job, message="missing execution_plan_id in run_check job payload")
            return

        parsed_page_check_id: UUID | None = None
        if execution_track == "realtime_probe":
            if page_check_id is not None:
                if not isinstance(page_check_id, str):
                    await self._mark_failed(job, message="invalid page_check_id in run_check job payload")
                    return
                parsed_page_check_id = _parse_uuid(page_check_id)
                if parsed_page_check_id is None:
                    await self._mark_failed(job, message="invalid page_check_id in run_check job payload")
                    return
        else:
            if not isinstance(page_check_id, str):
                await self._mark_failed(job, message="missing page_check_id in run_check job payload")
                return
            parsed_page_check_id = _parse_uuid(page_check_id)
            if parsed_page_check_id is None:
                await self._mark_failed(job, message="invalid page_check_id in run_check job payload")
                return

        raw_execution_request_id = job.payload.get("execution_request_id")
        execution_request_id = (
            raw_execution_request_id if isinstance(raw_execution_request_id, str) else None
        )
        parsed_execution_request_id = _parse_uuid(execution_request_id) if execution_request_id else None
        if execution_request_id is not None and parsed_execution_request_id is None:
            await self._mark_failed(job, message="invalid execution_request_id in run_check job payload")
            return
        execution_request = None
        if parsed_execution_request_id is not None:
            execution_request = await self._get(ExecutionRequest, parsed_execution_request_id)
            if execution_request is None:
                await self._mark_failed(
                    job,
                    message=f"execution request {parsed_execution_request_id} not found",
                )
                return
        runtime_inputs = (
            execution_request.template_params
            if execution_request is not None and isinstance(execution_request.template_params, dict)
            else None
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
        if execution_track != "realtime_probe" and parsed_page_check_id is not None:
            skip_reason = await self._resolve_retirement_skip_reason(
                page_check_id=parsed_page_check_id,
                published_job_id=published_job_id,
            )
            if skip_reason is not None:
                await self._mark_skipped(job, message=skip_reason, job_run=job_run)
                return

        job.status = QueuedJobStatus.RUNNING.value
        job.started_at = job.started_at or utcnow()
        if job_run is not None:
            job_run.run_status = QueuedJobStatus.RUNNING.value
            job_run.started_at = job_run.started_at or utcnow()
        await self._commit()

        precompiled_retry_payload: dict[str, object] | None = None
        try:
            if execution_track == "realtime_probe":
                result = await self.runner_service.run_realtime_probe(
                    execution_plan_id=parsed_execution_plan_id,
                )
                if (
                    result.status.value == "passed"
                    and parsed_execution_plan_id is not None
                    and self.control_plane_service is not None
                ):
                    await self.control_plane_service.persist_realtime_probe_feedback(
                        execution_plan_id=parsed_execution_plan_id,
                        execution_run_id=result.execution_run_id,
                    )
            elif execution_track == "precompiled":
                result, precompiled_retry_payload = await self._run_precompiled_with_retry(
                    page_check_id=parsed_page_check_id,
                    execution_plan_id=parsed_execution_plan_id,
                    runtime_inputs=runtime_inputs,
                )
            else:
                result = await self.runner_service.run_page_check(
                    page_check_id=parsed_page_check_id,
                    execution_plan_id=parsed_execution_plan_id,
                    runtime_inputs=runtime_inputs,
                )
        except PrecompiledRetryBlockedError as exc:
            await self._mark_skipped(
                job,
                message=ASSET_RETIRED_FAILURE_MESSAGE,
                job_run=job_run,
                result_payload_kwargs=exc.retry_payload,
            )
            return
        except ExecutionBlockedError:
            await self._mark_skipped(
                job,
                message=ASSET_RETIRED_FAILURE_MESSAGE,
                job_run=job_run,
            )
            return
        except PrecompiledRetryTerminalError as exc:
            await self._mark_failed(
                job,
                message=str(exc),
                job_run=job_run,
                result_payload_kwargs=exc.retry_payload,
            )
            return
        except Exception as exc:
            await self._mark_failed(job, message=str(exc), job_run=job_run)
            return

        job.status = QueuedJobStatus.COMPLETED.value
        job.finished_at = utcnow()
        job.failure_message = None
        result_payload_kwargs: dict[str, object] = precompiled_retry_payload or {}
        job.result_payload = self._build_result_payload(
            job=job,
            queue_status=job.status,
            execution_status=result.status.value,
            execution_request_id=execution_request_id,
            execution_plan_id=execution_plan_id,
            execution_run_id=str(result.execution_run_id),
            auth_status=result.auth_status.value,
            artifact_ids=[str(artifact_id) for artifact_id in result.artifact_ids],
            page_check_id=str(result.page_check_id) if result.page_check_id is not None else None,
            **result_payload_kwargs,
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
        result_payload_kwargs: dict[str, object] | None = None,
    ) -> None:
        job.status = QueuedJobStatus.FAILED.value
        job.started_at = job.started_at or utcnow()
        job.finished_at = utcnow()
        job.failure_message = message
        payload_kwargs = result_payload_kwargs or {}
        job.result_payload = self._build_result_payload(
            job=job,
            queue_status=job.status,
            execution_status="failed",
            error_message=message,
            **payload_kwargs,
        )
        if job_run is not None:
            job_run.run_status = QueuedJobStatus.FAILED.value
            job_run.started_at = job_run.started_at or utcnow()
            job_run.finished_at = utcnow()
            job_run.failure_message = message
        await self._commit()

    async def _mark_skipped(
        self,
        job: QueuedJob,
        *,
        message: str | None,
        job_run: JobRun | None = None,
        result_payload_kwargs: dict[str, object] | None = None,
    ) -> None:
        job.status = QueuedJobStatus.SKIPPED.value
        job.started_at = job.started_at or utcnow()
        job.finished_at = utcnow()
        job.failure_message = message
        payload_kwargs = result_payload_kwargs or {}
        job.result_payload = self._build_result_payload(
            job=job,
            queue_status=job.status,
            execution_status="skipped",
            error_message=message,
            **payload_kwargs,
        )
        if job_run is not None:
            job_run.run_status = QueuedJobStatus.SKIPPED.value
            job_run.started_at = job_run.started_at or utcnow()
            job_run.finished_at = utcnow()
            job_run.failure_message = message
        await self._commit()

    async def _resolve_retirement_skip_reason(
        self,
        *,
        page_check_id: UUID,
        published_job_id: UUID | None,
    ) -> str | None:
        page_check = await self._get(PageCheck, page_check_id)
        if page_check is None:
            return "asset_retired_missing"
        check_retired_reason = _retirement_failure_message(page_check.lifecycle_status)
        if check_retired_reason is not None:
            return check_retired_reason

        page_asset = await self._get(PageAsset, page_check.page_asset_id)
        if page_asset is None:
            return "asset_retired_missing"
        asset_retired_reason = _retirement_failure_message(page_asset.lifecycle_status)
        if asset_retired_reason is not None:
            return asset_retired_reason

        if published_job_id is None:
            return None
        published_job = await self._get(PublishedJob, published_job_id)
        if published_job is None:
            return None
        if published_job.state != PublishedJobState.PAUSED:
            return None
        if _is_retired_pause_marker(published_job):
            return ASSET_RETIRED_FAILURE_MESSAGE
        return None

    async def _run_precompiled_with_retry(
        self,
        *,
        page_check_id: UUID | None,
        execution_plan_id: UUID | None,
        runtime_inputs: dict[str, object] | None = None,
    ):
        attempts: list[dict[str, object]] = []
        last_result = None
        final_failure_category: str | None = None
        final_error_message: str | None = None
        final_retryable = False
        for attempt_no in range(1, _PRECOMPILED_MAX_ATTEMPTS + 1):
            started_at = utcnow()
            try:
                result = await self.runner_service.run_page_check(
                    page_check_id=page_check_id,
                    execution_plan_id=execution_plan_id,
                    runtime_inputs=runtime_inputs,
                )
            except ExecutionBlockedError as exc:
                if not attempts:
                    raise
                raise PrecompiledRetryBlockedError(
                    message=str(exc),
                    retry_payload=self._build_precompiled_retry_payload(
                        attempt_count=len(attempts),
                        flaky=False,
                        retry_exhausted=False,
                        attempts=attempts,
                        final_failure_category=final_failure_category,
                        final_error_message=final_error_message,
                    ),
                ) from exc
            except Exception as exc:
                finished_at = utcnow()
                await self._rollback()
                retryable = is_retryable_failure(
                    failure_category="runtime_error",
                    error_message=str(exc),
                )
                should_retry = retryable and attempt_no < _PRECOMPILED_MAX_ATTEMPTS
                backoff_ms = (
                    compute_backoff_ms(
                        attempt_no=attempt_no,
                        base_backoff_ms=_PRECOMPILED_BASE_BACKOFF_MS,
                        jitter_ms=_PRECOMPILED_JITTER_MS,
                    )
                    if should_retry
                    else 0
                )
                attempts.append(
                    build_attempt_entry(
                        attempt_no=attempt_no,
                        started_at=started_at,
                        finished_at=finished_at,
                        status="failed",
                        failure_category="runtime_error",
                        retryable=retryable,
                        backoff_ms=backoff_ms,
                    )
                )
                final_failure_category = "runtime_error"
                final_error_message = str(exc)
                final_retryable = retryable
                if not should_retry:
                    raise PrecompiledRetryTerminalError(
                        message=str(exc),
                        retry_payload=self._build_precompiled_retry_payload(
                            attempt_count=attempt_no,
                            flaky=False,
                            retry_exhausted=retryable and attempt_no >= _PRECOMPILED_MAX_ATTEMPTS,
                            attempts=attempts,
                            final_failure_category=final_failure_category,
                            final_error_message=final_error_message,
                        ),
                    ) from exc
                await self._sleep_for_backoff(backoff_ms=backoff_ms)
                continue

            finished_at = utcnow()
            last_result = result
            if _enum_value(result.status) == "passed":
                attempts.append(
                    build_attempt_entry(
                        attempt_no=attempt_no,
                        started_at=started_at,
                        finished_at=finished_at,
                        status="passed",
                        failure_category=None,
                        retryable=False,
                        backoff_ms=0,
                    )
                )
                return result, self._build_precompiled_retry_payload(
                    attempt_count=attempt_no,
                    flaky=attempt_no > 1,
                    retry_exhausted=False,
                    attempts=attempts,
                    final_failure_category=None,
                    final_error_message=None,
                )

            failure_category = _enum_value(getattr(result, "failure_category", None))
            error_message = self._extract_error_message(result)
            retryable = is_retryable_failure(
                failure_category=failure_category,
                error_message=error_message,
            )
            should_retry = retryable and attempt_no < _PRECOMPILED_MAX_ATTEMPTS
            backoff_ms = (
                compute_backoff_ms(
                    attempt_no=attempt_no,
                    base_backoff_ms=_PRECOMPILED_BASE_BACKOFF_MS,
                    jitter_ms=_PRECOMPILED_JITTER_MS,
                )
                if should_retry
                else 0
            )
            attempts.append(
                build_attempt_entry(
                    attempt_no=attempt_no,
                    started_at=started_at,
                    finished_at=finished_at,
                    status="failed",
                    failure_category=failure_category,
                    retryable=retryable,
                    backoff_ms=backoff_ms,
                )
            )
            final_failure_category = failure_category
            final_error_message = error_message
            final_retryable = retryable
            if not should_retry:
                return result, self._build_precompiled_retry_payload(
                    attempt_count=attempt_no,
                    flaky=attempt_no > 1 and _enum_value(result.status) == "passed",
                    retry_exhausted=retryable and attempt_no >= _PRECOMPILED_MAX_ATTEMPTS,
                    attempts=attempts,
                    final_failure_category=failure_category,
                    final_error_message=error_message,
                )

            await self._sleep_for_backoff(backoff_ms=backoff_ms)

        return last_result, self._build_precompiled_retry_payload(
            attempt_count=_PRECOMPILED_MAX_ATTEMPTS,
            flaky=False,
            retry_exhausted=final_retryable,
            attempts=attempts,
            final_failure_category=final_failure_category,
            final_error_message=final_error_message,
        )

    async def _sleep_for_backoff(self, *, backoff_ms: int) -> None:
        if backoff_ms <= 0:
            return
        await anyio.sleep(backoff_ms / 1000)

    def _build_precompiled_retry_payload(
        self,
        *,
        attempt_count: int,
        flaky: bool,
        retry_exhausted: bool,
        attempts: list[dict[str, object]],
        final_failure_category: str | None,
        final_error_message: str | None,
    ) -> dict[str, object]:
        return {
            "attempt_count": attempt_count,
            "retry_exhausted": retry_exhausted,
            "flaky": flaky,
            "retry_policy": {
                "max_attempts": _PRECOMPILED_MAX_ATTEMPTS,
                "base_backoff_ms": _PRECOMPILED_BASE_BACKOFF_MS,
                "jitter_ms": _PRECOMPILED_JITTER_MS,
            },
            "attempts": attempts,
            "final_failure_category": final_failure_category,
            "final_error_message": final_error_message,
        }

    def _extract_error_message(self, result) -> str | None:
        step_results = getattr(result, "step_results", None)
        if not step_results:
            return None
        for step_result in step_results:
            if _enum_value(getattr(step_result, "status", None)) != "failed":
                continue
            detail = getattr(step_result, "detail", None)
            if detail is not None:
                normalized = str(detail).strip()
                if normalized:
                    return normalized
        return None

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
        page_check_id: str | None | object = _UNSET,
        attempt_count: int | None | object = _UNSET,
        retry_exhausted: bool | None | object = _UNSET,
        flaky: bool | None | object = _UNSET,
        retry_policy: dict[str, object] | None | object = _UNSET,
        attempts: list[dict[str, object]] | None | object = _UNSET,
        final_failure_category: str | None | object = _UNSET,
        final_error_message: str | None | object = _UNSET,
    ) -> dict[str, object]:
        payload = job.payload
        resolved_page_check_id = (
            _optional_string(payload.get("page_check_id"))
            if page_check_id is _UNSET
            else _optional_string(page_check_id)
        )
        result = {
            "queued_job_id": str(job.id),
            "queue_status": queue_status,
            "status": execution_status,
            "page_check_id": resolved_page_check_id,
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
        if attempt_count is not _UNSET:
            result["attempt_count"] = attempt_count
        if retry_exhausted is not _UNSET:
            result["retry_exhausted"] = retry_exhausted
        if flaky is not _UNSET:
            result["flaky"] = flaky
        if retry_policy is not _UNSET:
            result["retry_policy"] = retry_policy
        if attempts is not _UNSET:
            result["attempts"] = attempts
        if final_failure_category is not _UNSET:
            result["final_failure_category"] = final_failure_category
        if final_error_message is not _UNSET:
            result["final_error_message"] = final_error_message
        return result

    async def _get(self, model, identifier):
        if isinstance(self.session, AsyncSession):
            return await self.session.get(model, identifier)
        return self.session.get(model, identifier)

    async def _commit(self) -> None:
        if isinstance(self.session, AsyncSession):
            await self.session.commit()
            return
        self.session.commit()

    async def _rollback(self) -> None:
        if isinstance(self.session, AsyncSession):
            await self.session.rollback()
            return
        self.session.rollback()


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _enum_value(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "value"):
        return str(getattr(value, "value")).strip().lower()
    text = str(value).strip().lower()
    return text or None


def _parse_uuid(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except (TypeError, ValueError):
        return None


def _retirement_failure_message(
    lifecycle_status: AssetLifecycleStatus | str | None,
) -> str | None:
    if lifecycle_status is None:
        return None
    normalized = (
        lifecycle_status.value
        if isinstance(lifecycle_status, AssetLifecycleStatus)
        else str(lifecycle_status).strip().lower()
    )
    if normalized == AssetLifecycleStatus.ACTIVE.value:
        return None
    return ASSET_RETIRED_FAILURE_MESSAGE


def _is_retired_pause_marker(published_job: PublishedJob) -> bool:
    normalized_reason = (published_job.pause_reason or "").strip().lower()
    if "retired" not in normalized_reason:
        return False
    return any(
        (
            published_job.paused_by_snapshot_id is not None,
            published_job.paused_by_asset_id is not None,
            published_job.paused_by_page_check_id is not None,
        )
    )
