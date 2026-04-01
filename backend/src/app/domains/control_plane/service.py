from __future__ import annotations

from app.domains.control_plane.job_types import RUN_CHECK_JOB_TYPE
from app.domains.control_plane.repository import ControlPlaneRepository
from app.domains.control_plane.schemas import CheckRequestAccepted, CreateCheckRequest
from app.infrastructure.queue.dispatcher import QueueDispatcher


DEFAULT_AUTH_POLICY = "server_injected"


class ControlPlaneService:
    def __init__(
        self,
        *,
        repository: ControlPlaneRepository,
        dispatcher: QueueDispatcher,
    ) -> None:
        self.repository = repository
        self.dispatcher = dispatcher

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

        request = await self.repository.create_execution_request(payload=payload)
        plan = await self.repository.create_execution_plan(
            execution_request_id=request.id,
            resolved_system_id=system.id if system else None,
            resolved_page_asset_id=page_asset.id if page_asset else None,
            resolved_page_check_id=page_check.id if page_check else None,
            execution_track=execution_track,
            auth_policy=DEFAULT_AUTH_POLICY,
            module_plan_id=page_check.module_plan_id if page_check else None,
        )
        job_id = await self.dispatcher.enqueue(
            job_type=RUN_CHECK_JOB_TYPE,
            payload={
                "execution_plan_id": str(plan.id),
                "execution_request_id": str(request.id),
                "page_check_id": str(page_check.id) if page_check else None,
                "execution_track": execution_track,
            },
        )

        return CheckRequestAccepted(
            request_id=request.id,
            plan_id=plan.id,
            page_check_id=page_check.id if page_check else None,
            execution_track=execution_track,
            auth_policy=DEFAULT_AUTH_POLICY,
            job_id=job_id,
        )
