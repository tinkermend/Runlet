from __future__ import annotations

import inspect
from datetime import UTC, datetime
from uuid import UUID

from sqlmodel import Session, desc, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.domains.runner_service.module_executor import ModuleExecutor, RunnerRuntime
from app.domains.runner_service.schemas import RunPageCheckResult, RunnerRunStatus
from app.infrastructure.db.models.assets import ModulePlan, PageAsset, PageCheck
from app.infrastructure.db.models.crawl import Page
from app.infrastructure.db.models.execution import (
    ExecutionArtifact,
    ExecutionPlan,
    ExecutionRequest,
    ExecutionRun,
)
from app.infrastructure.db.models.systems import AuthState, System
from app.shared.enums import AssetLifecycleStatus, ExecutionResultStatus


def utcnow() -> datetime:
    return datetime.now(UTC)


class ExecutionBlockedError(ValueError):
    def __init__(self, *, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RunnerService:
    def __init__(
        self,
        *,
        session: Session | AsyncSession,
        runtime: RunnerRuntime,
        module_executor: ModuleExecutor | None = None,
    ) -> None:
        self.session = session
        self.runtime = runtime
        self.module_executor = module_executor or ModuleExecutor(runtime=runtime)

    async def run_page_check(
        self,
        *,
        page_check_id: UUID,
        execution_plan_id: UUID | None = None,
    ) -> RunPageCheckResult:
        page_check = await self._get(PageCheck, page_check_id)
        if page_check is None:
            raise ValueError(f"page check {page_check_id} not found")
        check_retired_reason = _retirement_failure_message(page_check.lifecycle_status)
        if check_retired_reason is not None:
            raise ExecutionBlockedError(reason=check_retired_reason)
        if page_check.module_plan_id is None:
            raise ValueError(f"page check {page_check_id} has no module plan")

        module_plan = await self._get(ModulePlan, page_check.module_plan_id)
        if module_plan is None:
            raise ValueError(f"module plan {page_check.module_plan_id} not found")

        page_asset = await self._get(PageAsset, page_check.page_asset_id)
        if page_asset is None:
            raise ValueError(f"page asset {page_check.page_asset_id} not found")
        asset_retired_reason = _retirement_failure_message(page_asset.lifecycle_status)
        if asset_retired_reason is not None:
            raise ExecutionBlockedError(reason=asset_retired_reason)

        page = await self._get(Page, page_asset.page_id)
        if page is None:
            raise ValueError(f"page {page_asset.page_id} not found")

        system = await self._get(System, page_asset.system_id)
        if system is None:
            raise ValueError(f"system {page_asset.system_id} not found")

        auth_state = await self._load_valid_auth_state(system_id=system.id)
        if auth_state is None or auth_state.storage_state is None:
            raise ValueError(f"valid auth state not found for system {system.id}")

        execution_plan = await self._resolve_execution_plan(
            execution_plan_id=execution_plan_id,
            page_check=page_check,
            page_asset=page_asset,
            system=system,
            module_plan=module_plan,
        )

        execution_run = ExecutionRun(
            execution_plan_id=execution_plan.id,
            status=RunnerRunStatus.RUNNING.value,
            asset_version=page_asset.asset_version,
        )
        self.session.add(execution_run)
        await self._flush()

        await self._configure_runtime(base_url=system.base_url)
        try:
            execution_result = await self.module_executor.execute(
                steps_json=module_plan.steps_json,
                storage_state=auth_state.storage_state,
            )
        finally:
            await self._close_runtime()

        execution_run.status = execution_result.status.value
        execution_run.auth_status = execution_result.auth_status.value
        execution_run.duration_ms = 0

        artifact = ExecutionArtifact(
            execution_run_id=execution_run.id,
            artifact_kind="module_execution",
            result_status=(
                ExecutionResultStatus.SUCCESS
                if execution_result.status == RunnerRunStatus.PASSED
                else ExecutionResultStatus.FAILED
            ),
            payload={
                "page_check_id": str(page_check.id),
                "page_asset_id": str(page_asset.id),
                "system_id": str(system.id),
                "step_results": [step.model_dump(mode="json") for step in execution_result.step_results],
            },
        )
        self.session.add(artifact)

        await self._commit()
        await self._refresh(execution_run)
        await self._refresh(artifact)

        return RunPageCheckResult(
            page_check_id=page_check.id,
            execution_run_id=execution_run.id,
            status=execution_result.status,
            auth_status=execution_result.auth_status,
            artifact_ids=[artifact.id],
            step_results=execution_result.step_results,
        )

    async def _resolve_execution_plan(
        self,
        *,
        execution_plan_id: UUID | None,
        page_check: PageCheck,
        page_asset: PageAsset,
        system: System,
        module_plan: ModulePlan,
    ) -> ExecutionPlan:
        if execution_plan_id is not None:
            plan = await self._get(ExecutionPlan, execution_plan_id)
            if plan is None:
                raise ValueError(f"execution plan {execution_plan_id} not found")
            return plan

        request = ExecutionRequest(
            request_source="runner_service",
            system_hint=system.code,
            page_hint=page_asset.asset_key,
            check_goal=page_check.goal,
            strictness="balanced",
            time_budget_ms=20_000,
        )
        self.session.add(request)
        await self._flush()

        plan = ExecutionPlan(
            execution_request_id=request.id,
            resolved_system_id=system.id,
            resolved_page_asset_id=page_asset.id,
            resolved_page_check_id=page_check.id,
            execution_track="precompiled",
            auth_policy="server_injected",
            module_plan_id=module_plan.id,
        )
        self.session.add(plan)
        await self._flush()
        return plan

    async def _load_valid_auth_state(self, *, system_id: UUID) -> AuthState | None:
        statement = (
            select(AuthState)
            .where(AuthState.system_id == system_id)
            .where(AuthState.status == "valid")
            .where(AuthState.is_valid.is_(True))
            .order_by(desc(AuthState.validated_at), desc(AuthState.id))
        )
        return await self._exec_first(statement)

    async def _get(self, model, identifier):
        if isinstance(self.session, AsyncSession):
            return await self.session.get(model, identifier)
        return self.session.get(model, identifier)

    async def _exec_first(self, statement):
        if isinstance(self.session, AsyncSession):
            result = await self.session.exec(statement)
            return result.first()
        return self.session.exec(statement).first()

    async def _flush(self) -> None:
        if isinstance(self.session, AsyncSession):
            await self.session.flush()
            return
        self.session.flush()

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

    async def _configure_runtime(self, *, base_url: str) -> None:
        setter = getattr(self.runtime, "set_base_url", None)
        if not callable(setter):
            return
        result = setter(base_url)
        if inspect.isawaitable(result):
            await result

    async def _close_runtime(self) -> None:
        closer = getattr(self.runtime, "close", None)
        if not callable(closer):
            return
        result = closer()
        if inspect.isawaitable(result):
            await result


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
    if normalized.startswith("retired_"):
        return f"asset_{normalized}"
    return "asset_retired_missing"
