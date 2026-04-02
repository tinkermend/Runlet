from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException

from app.domains.control_plane.job_types import (
    ASSET_COMPILE_JOB_TYPE,
    AUTH_REFRESH_JOB_TYPE,
    CRAWL_JOB_TYPE,
    RUN_CHECK_JOB_TYPE,
)
from app.domains.control_plane.repository import ControlPlaneRepository
from app.domains.control_plane.scheduler_registry import SchedulerRegistry
from app.domains.control_plane.schemas import (
    AuthRefreshAccepted,
    CheckRequestAccepted,
    CheckRequestStatus,
    CompileAssetsAccepted,
    CompileAssetsRequest,
    CreateCheckRequest,
    CrawlAccepted,
    CrawlTriggerRequest,
    PageAssetChecksList,
    RunPageCheck,
)
from app.domains.runner_service.script_renderer import RenderScriptResult
from app.domains.runner_service.scheduler import (
    CreatePublishedJobRequest,
    PublishedJobCreated,
    PublishedJobRunsList,
    PublishedJobService,
    PublishedJobTriggerAccepted,
)
from app.infrastructure.queue.dispatcher import QueueDispatcher


DEFAULT_AUTH_POLICY = "server_injected"


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
    ) -> CheckRequestAccepted:
        payload = CreateCheckRequest(
            system_hint=system_hint,
            page_hint=page_hint,
            check_goal=check_goal,
            strictness=strictness,
            time_budget_ms=time_budget_ms,
            request_source=request_source,
        )

        system = await self.repository.resolve_system(system_hint=payload.system_hint)
        page_asset, page_check = await self.repository.resolve_page_asset_and_check(
            system_hint=payload.system_hint,
            system_id=system.id if system else None,
            page_hint=payload.page_hint,
            check_goal=payload.check_goal,
        )
        execution_track = "precompiled" if page_check is not None else "realtime"
        return await self._accept_check_request(
            payload=payload,
            resolved_system_id=system.id if system else None,
            resolved_page_asset_id=page_asset.id if page_asset else None,
            resolved_page_check_id=page_check.id if page_check else None,
            module_plan_id=page_check.module_plan_id if page_check else None,
            execution_track=execution_track,
        )

    async def get_check_request_status(self, request_id: UUID) -> CheckRequestStatus:
        status = await self.repository.get_check_request_status(request_id=request_id)
        if status is None:
            raise HTTPException(status_code=404, detail="check request not found")
        return status

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
            raise HTTPException(status_code=404, detail="page check not found")

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
            if self.scheduler_registry is not None:
                await self.scheduler_registry.upsert_published_job(created.published_job_id)
            return created
        except ValueError as exc:
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
        except ValueError as exc:
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
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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
