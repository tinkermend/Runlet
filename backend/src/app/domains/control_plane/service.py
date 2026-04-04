from __future__ import annotations

import logging
from typing import Literal
from uuid import UUID

from fastapi import HTTPException

from app.domains.asset_compiler.template_registry import get_template
from app.domains.control_plane.job_types import (
    ASSET_COMPILE_JOB_TYPE,
    AUTH_REFRESH_JOB_TYPE,
    CRAWL_JOB_TYPE,
    RUN_CHECK_JOB_TYPE,
)
from app.domains.control_plane.repository import ControlPlaneRepository
from app.domains.control_plane.recommendation import rank_candidates
from app.domains.control_plane.runtime_policies import (
    InvalidRuntimePolicyScheduleError,
    UpsertSystemAuthPolicy,
    UpsertSystemCrawlPolicy,
    is_policy_effectively_active,
    validate_policy_schedule_expr,
)
from app.domains.control_plane.scheduler_registry import (
    SchedulerRegistry,
    build_auth_policy_job_id,
    build_crawl_policy_job_id,
)
from app.domains.control_plane.schemas import (
    AuthRefreshAccepted,
    CheckRequestAccepted,
    CheckRequestStatus,
    CompileAssetsAccepted,
    CompileAssetsRequest,
    CheckCandidateItem,
    CheckCandidatesRequest,
    CheckCandidatesResponse,
    CreateCheckRequest,
    CrawlAccepted,
    SystemAuthPolicyRead,
    SystemCrawlPolicyRead,
    CrawlTriggerRequest,
    PageAssetChecksList,
    PublishCheckRequest,
    ReconciliationCascadeApplied,
    RunPageCheck,
    UpdateSystemAuthPolicy,
    UpdateSystemCrawlPolicy,
)
from app.domains.runner_service.result_views import CheckResultView
from app.domains.runner_service.script_renderer import RenderScriptResult
from app.domains.runner_service.scheduler import (
    CreatePublishedJobRequest,
    InvalidPublishedJobScheduleError,
    PublishedJobCreated,
    PublishedJobNotFoundError,
    PublishedJobRunsList,
    PublishedJobService,
    PublishedJobTriggerAccepted,
)
from app.infrastructure.queue.dispatcher import QueueDispatcher
from app.shared.enums import AssetLifecycleStatus


DEFAULT_AUTH_POLICY = "server_injected"
logger = logging.getLogger(__name__)


class ControlPlaneService:
    def __init__(
        self,
        *,
        repository: ControlPlaneRepository,
        dispatcher: QueueDispatcher,
        script_renderer=None,
        published_job_service: PublishedJobService | None = None,
        scheduler_registry: SchedulerRegistry | None = None,
    ) -> None:
        self.repository = repository
        self.dispatcher = dispatcher
        self.script_renderer = script_renderer
        self.published_job_service = published_job_service
        self.scheduler_registry = scheduler_registry

    async def submit_check_request(
        self,
        *,
        system_hint: str,
        page_hint: str | None = None,
        check_goal: str,
        strictness: str = "balanced",
        time_budget_ms: int = 20_000,
        request_source: str = "api",
        template_code: str | None = None,
        template_version: str | None = None,
        carrier_hint: Literal["table", "list"] | None = None,
        template_params: dict[str, object] | None = None,
    ) -> CheckRequestAccepted:
        payload = CreateCheckRequest(
            system_hint=system_hint,
            page_hint=page_hint,
            check_goal=check_goal,
            strictness=strictness,
            time_budget_ms=time_budget_ms,
            request_source=request_source,
            template_code=template_code,
            template_version=template_version,
            carrier_hint=carrier_hint,
            template_params=template_params,
        )
        self._assert_readonly_template_request(payload=payload)

        resolution = await self.repository.resolve_page_asset_and_check(
            system_hint=payload.system_hint,
            page_hint=payload.page_hint,
            check_goal=payload.check_goal,
        )
        system = resolution.system
        page_asset = resolution.page_asset
        page_check = resolution.page_check

        if page_asset is not None and page_asset.lifecycle_status != AssetLifecycleStatus.ACTIVE:
            raise HTTPException(status_code=409, detail="asset is retired")
        if page_check is not None and page_check.lifecycle_status != AssetLifecycleStatus.ACTIVE:
            raise HTTPException(status_code=409, detail="page check is retired")
        if page_check is None:
            retired_target = await self.repository.resolve_retired_page_asset_or_check(
                system_hint=payload.system_hint,
                system_id=system.id if system else None,
                page_hint=payload.page_hint,
                check_goal=payload.check_goal,
            )
            if retired_target is not None:
                detail = "page check is retired" if retired_target.page_check is not None else "asset is retired"
                raise HTTPException(status_code=409, detail=detail)
        if resolution.miss_reason == "element_asset_missing":
            raise HTTPException(status_code=409, detail="element asset is missing")

        execution_track = "precompiled" if page_check is not None else "realtime_probe"
        return await self._accept_check_request(
            payload=payload,
            resolved_system_id=system.id if system else None,
            resolved_page_asset_id=page_asset.id if page_asset else None,
            resolved_page_check_id=page_check.id if page_check else None,
            module_plan_id=page_check.module_plan_id if page_check else None,
            execution_track=execution_track,
        )

    async def get_check_candidates(
        self,
        *,
        system_hint: str,
        page_hint: str | None,
        intent: str,
        slot_hints: dict[str, object] | None = None,
    ) -> CheckCandidatesResponse:
        payload = CheckCandidatesRequest(
            system_hint=system_hint,
            page_hint=page_hint,
            intent=intent,
            slot_hints=slot_hints,
        )
        candidates = await self.repository.list_check_candidates(
            system_hint=payload.system_hint,
            page_hint=payload.page_hint,
        )
        ranked = rank_candidates(candidates)
        top_candidates = [
            CheckCandidateItem(
                page_asset_id=item.page_asset_id,
                page_check_id=item.page_check_id,
                asset_key=item.asset_key,
                check_code=item.check_code,
                goal=item.goal,
                alias_confidence=item.alias_confidence,
                success_rate=item.success_rate,
                sample_count=item.sample_count,
                recency_score=item.recency_score,
                rank_score=item.rank_score,
            )
            for item in ranked[:3]
        ]
        return CheckCandidatesResponse(candidates=top_candidates)

    async def get_check_request_status(self, request_id: UUID) -> CheckRequestStatus:
        status = await self.repository.get_check_request_status(request_id=request_id)
        if status is None:
            raise HTTPException(status_code=404, detail="check request not found")
        return status

    async def get_check_request_result(self, request_id: UUID) -> CheckResultView:
        result = await self.repository.get_check_request_result_view(request_id=request_id)
        if result is None:
            raise HTTPException(status_code=404, detail="check request not found")
        return result

    async def persist_realtime_probe_feedback(
        self,
        *,
        execution_plan_id: UUID,
        execution_run_id: UUID,
    ) -> None:
        plan = await self.repository.get_execution_plan(execution_plan_id=execution_plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="execution plan not found")
        if plan.execution_track != "realtime_probe":
            raise HTTPException(status_code=409, detail="execution plan is not realtime_probe")
        if plan.resolved_page_asset_id is None:
            raise HTTPException(status_code=409, detail="page asset is not resolved in execution plan")

        execution_run = await self.repository.get_execution_run(
            execution_run_id=execution_run_id
        )
        latest_run = await self.repository.get_latest_execution_run(
            execution_plan_id=execution_plan_id
        )
        if (
            execution_run is None
            or execution_run.execution_plan_id != execution_plan_id
            or execution_run.status != "passed"
            or latest_run is None
            or latest_run.id != execution_run_id
        ):
            raise HTTPException(status_code=409, detail="realtime probe execution is not successful")

        request = await self.repository.get_execution_request(
            execution_request_id=plan.execution_request_id
        )
        if request is None:
            raise HTTPException(status_code=404, detail="execution request not found")

        page_asset = await self.repository.get_page_asset(
            page_asset_id=plan.resolved_page_asset_id
        )
        if page_asset is None:
            raise HTTPException(status_code=404, detail="page asset not found")

        page = await self.repository.get_page(page_id=page_asset.page_id)
        if page is None:
            raise HTTPException(status_code=404, detail="page not found")

        await self.repository.upsert_intent_alias(
            system_alias=request.system_hint,
            page_alias=request.page_hint,
            check_alias=request.check_goal,
            route_hint=page.route_path,
            asset_key=page_asset.asset_key,
            source="realtime_probe",
            confidence=1.0,
        )
        await self.repository.commit()

    async def run_page_check(
        self,
        *,
        page_check_id: UUID,
        strictness: str = "balanced",
        time_budget_ms: int = 20_000,
        triggered_by: str = "manual",
    ) -> CheckRequestAccepted:
        payload = RunPageCheck(
            strictness=strictness,
            time_budget_ms=time_budget_ms,
            triggered_by=triggered_by,
        )
        target = await self.repository.get_page_check_run_target(
            page_check_id=page_check_id,
        )
        if target is None:
            lookup = await self.repository.get_page_check_lookup(page_check_id=page_check_id)
            if lookup is None:
                raise HTTPException(status_code=404, detail="page check not found")
            if lookup.page_check.lifecycle_status != AssetLifecycleStatus.ACTIVE:
                raise HTTPException(status_code=409, detail="page check is retired")
            if lookup.page_asset.lifecycle_status != AssetLifecycleStatus.ACTIVE:
                raise HTTPException(status_code=409, detail="asset is retired")
            raise HTTPException(status_code=404, detail="page check not found")
        if target.page_check.lifecycle_status != AssetLifecycleStatus.ACTIVE:
            raise HTTPException(status_code=409, detail="page check is retired")
        if target.page_asset.lifecycle_status != AssetLifecycleStatus.ACTIVE:
            raise HTTPException(status_code=409, detail="asset is retired")

        return await self._accept_check_request(
            payload=CreateCheckRequest(
                system_hint=target.system.code,
                page_hint=target.page_asset.asset_key,
                check_goal=target.page_check.goal,
                strictness=payload.strictness,
                time_budget_ms=payload.time_budget_ms,
                request_source=payload.triggered_by,
            ),
            resolved_system_id=target.system.id,
            resolved_page_asset_id=target.page_asset.id,
            resolved_page_check_id=target.page_check.id,
            module_plan_id=target.page_check.module_plan_id,
            execution_track="precompiled",
        )

    async def list_page_asset_checks(self, page_asset_id: UUID) -> PageAssetChecksList:
        page_asset_checks = await self.repository.get_page_asset_checks(
            page_asset_id=page_asset_id,
        )
        if page_asset_checks is None:
            raise HTTPException(status_code=404, detail="page asset not found")
        return page_asset_checks

    async def render_page_check_script(
        self,
        *,
        page_check_id: UUID,
        render_mode: str,
    ) -> RenderScriptResult:
        if self.script_renderer is None:
            raise HTTPException(status_code=500, detail="script renderer is not configured")
        target = await self.repository.get_page_check_run_target(page_check_id=page_check_id)
        if target is None:
            raise HTTPException(status_code=404, detail="page check not found")
        return await self.script_renderer.render_page_check(
            page_check_id=target.page_check.id,
            render_mode=render_mode,
        )

    async def create_published_job(
        self,
        *,
        payload: CreatePublishedJobRequest,
    ) -> PublishedJobCreated:
        if self.published_job_service is None:
            raise HTTPException(status_code=500, detail="published job service is not configured")
        try:
            created = await self.published_job_service.create_published_job(payload=payload)
            await self._sync_published_job_registry_safely(
                published_job_id=created.published_job_id,
            )
            return created
        except InvalidPublishedJobScheduleError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except PublishedJobNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def publish_check_request(
        self,
        *,
        request_id: UUID,
        payload: PublishCheckRequest,
    ) -> PublishedJobCreated:
        if self.script_renderer is None:
            raise HTTPException(status_code=500, detail="script renderer is not configured")
        if self.published_job_service is None:
            raise HTTPException(status_code=500, detail="published job service is not configured")

        result = await self.repository.get_check_request_result_view(request_id=request_id)
        if result is None:
            raise HTTPException(status_code=404, detail="check request not found")
        if result.plan_id is None or result.execution_summary is None:
            raise HTTPException(status_code=409, detail="check request has no successful execution")
        if result.execution_summary.status != "passed":
            raise HTTPException(status_code=409, detail="check request has no successful execution")
        if result.page_check_id is None:
            raise HTTPException(status_code=409, detail="check request has no publishable page_check")

        try:
            created = await self.published_job_service.create_published_job_from_execution(
                execution_plan_id=result.plan_id,
                page_check_id=result.page_check_id,
                schedule_expr=payload.schedule_expr,
                trigger_source=payload.trigger_source,
                enabled=payload.enabled,
                script_renderer=self.script_renderer,
            )
            await self._sync_published_job_registry_safely(
                published_job_id=created.published_job_id,
            )
            return created
        except InvalidPublishedJobScheduleError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except PublishedJobNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def trigger_published_job(
        self,
        *,
        published_job_id: UUID,
        trigger_source: str = "manual",
    ) -> PublishedJobTriggerAccepted:
        if self.published_job_service is None:
            raise HTTPException(status_code=500, detail="published job service is not configured")
        try:
            return await self.published_job_service.trigger_published_job(
                published_job_id=published_job_id,
                trigger_source=trigger_source,
            )
        except PublishedJobNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def list_published_job_runs(
        self,
        *,
        published_job_id: UUID,
    ) -> PublishedJobRunsList:
        if self.published_job_service is None:
            raise HTTPException(status_code=500, detail="published job service is not configured")
        try:
            return await self.published_job_service.list_published_job_runs(
                published_job_id=published_job_id,
            )
        except PublishedJobNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def get_system_auth_policy(self, *, system_id: UUID) -> SystemAuthPolicyRead:
        system = await self.repository.get_system_by_id(system_id=system_id)
        if system is None:
            raise HTTPException(status_code=404, detail="system not found")
        policy = await self.repository.get_system_auth_policy(system_id=system_id)
        if policy is None:
            raise HTTPException(status_code=404, detail="auth policy not found")
        return SystemAuthPolicyRead.model_validate(policy)

    async def upsert_system_auth_policy(
        self,
        *,
        system_id: UUID,
        payload: UpdateSystemAuthPolicy,
    ) -> SystemAuthPolicyRead:
        system = await self.repository.get_system_by_id(system_id=system_id)
        if system is None:
            raise HTTPException(status_code=404, detail="system not found")
        try:
            validate_policy_schedule_expr(payload.schedule_expr)
        except InvalidRuntimePolicyScheduleError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        try:
            policy = await self.repository.upsert_system_auth_policy(
                system_id=system_id,
                payload=UpsertSystemAuthPolicy(**payload.model_dump()),
            )
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise

        await self._sync_auth_policy_registry_safely(
            policy_id=policy.id,
            system_id=policy.system_id,
            enabled=policy.enabled,
            state=policy.state,
        )
        return SystemAuthPolicyRead.model_validate(policy)

    async def get_system_crawl_policy(self, *, system_id: UUID) -> SystemCrawlPolicyRead:
        system = await self.repository.get_system_by_id(system_id=system_id)
        if system is None:
            raise HTTPException(status_code=404, detail="system not found")
        policy = await self.repository.get_system_crawl_policy(system_id=system_id)
        if policy is None:
            raise HTTPException(status_code=404, detail="crawl policy not found")
        return SystemCrawlPolicyRead.model_validate(policy)

    async def upsert_system_crawl_policy(
        self,
        *,
        system_id: UUID,
        payload: UpdateSystemCrawlPolicy,
    ) -> SystemCrawlPolicyRead:
        system = await self.repository.get_system_by_id(system_id=system_id)
        if system is None:
            raise HTTPException(status_code=404, detail="system not found")
        try:
            validate_policy_schedule_expr(payload.schedule_expr)
        except InvalidRuntimePolicyScheduleError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        try:
            policy = await self.repository.upsert_system_crawl_policy(
                system_id=system_id,
                payload=UpsertSystemCrawlPolicy(**payload.model_dump()),
            )
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise

        await self._sync_crawl_policy_registry_safely(
            policy_id=policy.id,
            system_id=policy.system_id,
            enabled=policy.enabled,
            state=policy.state,
        )
        return SystemCrawlPolicyRead.model_validate(policy)

    async def refresh_auth(self, *, system_id: UUID) -> AuthRefreshAccepted:
        system = await self.repository.get_system_by_id(system_id=system_id)
        if system is None:
            raise HTTPException(status_code=404, detail="system not found")

        job_id = await self._enqueue_job(
            job_type=AUTH_REFRESH_JOB_TYPE,
            payload={"system_id": str(system.id)},
        )
        return AuthRefreshAccepted(system_id=system.id, job_id=job_id)

    async def trigger_crawl(
        self,
        *,
        system_id: UUID,
        payload: CrawlTriggerRequest,
    ) -> CrawlAccepted:
        system = await self.repository.get_system_by_id(system_id=system_id)
        if system is None:
            raise HTTPException(status_code=404, detail="system not found")

        job_id = await self._enqueue_job(
            job_type=CRAWL_JOB_TYPE,
            payload={
                "system_id": str(system.id),
                "crawl_scope": payload.crawl_scope,
                "framework_hint": payload.framework_hint,
                "max_pages": payload.max_pages,
            },
        )
        return CrawlAccepted(system_id=system.id, job_id=job_id)

    async def compile_assets(
        self,
        *,
        snapshot_id: UUID,
        payload: CompileAssetsRequest,
    ) -> CompileAssetsAccepted:
        snapshot = await self.repository.get_snapshot_by_id(snapshot_id=snapshot_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="snapshot not found")

        job_id = await self._enqueue_job(
            job_type=ASSET_COMPILE_JOB_TYPE,
            payload={
                "snapshot_id": str(snapshot.id),
                "compile_scope": payload.compile_scope,
            },
        )
        return CompileAssetsAccepted(snapshot_id=snapshot.id, job_id=job_id)

    async def apply_reconciliation_cascades(
        self,
        *,
        snapshot_id: UUID,
        alias_ids_to_disable: list[UUID],
        alias_ids_to_enable: list[UUID],
        published_job_ids_to_pause: list[UUID],
        published_job_ids_to_resume: list[UUID],
        alias_disable_decision_count: int = 0,
        alias_enable_decision_count: int = 0,
        published_job_pause_decision_count: int = 0,
        published_job_resume_decision_count: int = 0,
    ) -> ReconciliationCascadeApplied:
        try:
            aliases_disabled = await self.repository.disable_aliases_from_compiler_decisions(
                alias_ids=alias_ids_to_disable,
                snapshot_id=snapshot_id,
                reason="retired_missing",
            )
            aliases_enabled = await self.repository.enable_aliases_from_compiler_decisions(
                alias_ids=alias_ids_to_enable,
            )

            published_jobs_paused = 0
            published_jobs_resumed = 0
            if self.published_job_service is not None:
                published_jobs_paused = await self.published_job_service.pause_published_jobs_by_ids(
                    published_job_ids=published_job_ids_to_pause,
                    snapshot_id=snapshot_id,
                    reason="asset_retired_missing",
                    commit=False,
                )
                published_jobs_resumed = await self.published_job_service.resume_published_jobs_by_ids(
                    published_job_ids=published_job_ids_to_resume,
                    commit=False,
                )

            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise

        return ReconciliationCascadeApplied(
            snapshot_id=snapshot_id,
            alias_disable_decision_count=alias_disable_decision_count,
            alias_enable_decision_count=alias_enable_decision_count,
            published_job_pause_decision_count=published_job_pause_decision_count,
            published_job_resume_decision_count=published_job_resume_decision_count,
            aliases_disabled=aliases_disabled,
            aliases_enabled=aliases_enabled,
            published_jobs_paused=published_jobs_paused,
            published_jobs_resumed=published_jobs_resumed,
        )

    def _assert_readonly_template_request(self, *, payload: CreateCheckRequest) -> None:
        if payload.template_code is None:
            return
        template = get_template(
            template_code=payload.template_code,
            version=payload.template_version or "v1",
        )
        if template is None or not template.readonly:
            raise HTTPException(status_code=422, detail="readonly template required")

    async def _accept_check_request(
        self,
        *,
        payload: CreateCheckRequest,
        resolved_system_id: UUID | None,
        resolved_page_asset_id: UUID | None,
        resolved_page_check_id: UUID | None,
        module_plan_id: UUID | None,
        execution_track: str,
    ) -> CheckRequestAccepted:
        request = await self.repository.create_execution_request(payload=payload)
        try:
            plan = await self.repository.create_execution_plan(
                execution_request_id=request.id,
                resolved_system_id=resolved_system_id,
                resolved_page_asset_id=resolved_page_asset_id,
                resolved_page_check_id=resolved_page_check_id,
                execution_track=execution_track,
                auth_policy=DEFAULT_AUTH_POLICY,
                module_plan_id=module_plan_id,
            )
            job_id = await self.dispatcher.enqueue(
                job_type=RUN_CHECK_JOB_TYPE,
                payload={
                    "execution_plan_id": str(plan.id),
                    "execution_request_id": str(request.id),
                    "page_check_id": str(resolved_page_check_id)
                    if resolved_page_check_id
                    else None,
                    "execution_track": execution_track,
                },
            )
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise

        return CheckRequestAccepted(
            request_id=request.id,
            plan_id=plan.id,
            page_check_id=resolved_page_check_id,
            execution_track=execution_track,
            auth_policy=DEFAULT_AUTH_POLICY,
            job_id=job_id,
        )

    async def _enqueue_job(self, *, job_type: str, payload: dict[str, object]) -> UUID:
        try:
            job_id = await self.dispatcher.enqueue(job_type=job_type, payload=payload)
            await self.repository.commit()
            return job_id
        except Exception:
            await self.repository.rollback()
            raise

    async def _sync_auth_policy_registry(
        self,
        *,
        policy_id: UUID,
        system_id: UUID,
        enabled: bool,
        state: str,
    ) -> None:
        if self.scheduler_registry is None:
            return
        if is_policy_effectively_active(enabled=enabled, state=state):
            await self.scheduler_registry.upsert_auth_policy(policy_id)
            return
        self.scheduler_registry.remove_job(build_auth_policy_job_id(system_id))

    async def _sync_crawl_policy_registry(
        self,
        *,
        policy_id: UUID,
        system_id: UUID,
        enabled: bool,
        state: str,
    ) -> None:
        if self.scheduler_registry is None:
            return
        if is_policy_effectively_active(enabled=enabled, state=state):
            await self.scheduler_registry.upsert_crawl_policy(policy_id)
            return
        self.scheduler_registry.remove_job(build_crawl_policy_job_id(system_id))

    async def _sync_auth_policy_registry_safely(
        self,
        *,
        policy_id: UUID,
        system_id: UUID,
        enabled: bool,
        state: str,
    ) -> None:
        try:
            await self._sync_auth_policy_registry(
                policy_id=policy_id,
                system_id=system_id,
                enabled=enabled,
                state=state,
            )
        except Exception:
            logger.exception(
                "failed to sync auth policy registry: policy_id=%s system_id=%s",
                policy_id,
                system_id,
            )

    async def _sync_crawl_policy_registry_safely(
        self,
        *,
        policy_id: UUID,
        system_id: UUID,
        enabled: bool,
        state: str,
    ) -> None:
        try:
            await self._sync_crawl_policy_registry(
                policy_id=policy_id,
                system_id=system_id,
                enabled=enabled,
                state=state,
            )
        except Exception:
            logger.exception(
                "failed to sync crawl policy registry: policy_id=%s system_id=%s",
                policy_id,
                system_id,
            )

    async def _sync_published_job_registry(self, *, published_job_id: UUID) -> None:
        if self.scheduler_registry is None:
            return
        await self.scheduler_registry.upsert_published_job(published_job_id)

    async def _sync_published_job_registry_safely(self, *, published_job_id: UUID) -> None:
        try:
            await self._sync_published_job_registry(published_job_id=published_job_id)
        except Exception:
            logger.exception(
                "runtime mirror failure while syncing published job registry: published_job_id=%s",
                published_job_id,
            )


def _dedupe_uuids(values: list[UUID]) -> list[UUID]:
    deduped: list[UUID] = []
    seen: set[UUID] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
