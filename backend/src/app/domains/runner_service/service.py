from __future__ import annotations

import inspect
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.domains.runner_service.failure_categories import FailureCategory
from sqlmodel import Session, desc, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.domains.runner_service.module_executor import ModuleExecutor, RunnerRuntime
from app.domains.runner_service.schemas import (
    AuthInjectStatus,
    ModuleExecutionResult,
    PageProbePlan,
    RunPageCheckResult,
    RunnerRunStatus,
    StepExecutionResult,
)
from app.infrastructure.db.models.assets import ModulePlan, PageAsset, PageCheck
from app.infrastructure.db.models.crawl import Page
from app.infrastructure.db.models.execution import (
    ExecutionArtifact,
    ExecutionPlan,
    ExecutionRequest,
    ExecutionRun,
)
from app.infrastructure.db.models.systems import AuthState, System
from app.shared.enums import ExecutionResultStatus

_SCREENSHOT_ROOT = (
    Path(__file__).resolve().parents[4] / "generated" / "execution_artifacts" / "screenshots"
)


def utcnow() -> datetime:
    return datetime.now(UTC)


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
        if page_check.module_plan_id is None:
            raise ValueError(f"page check {page_check_id} has no module plan")

        module_plan = await self._get(ModulePlan, page_check.module_plan_id)
        if module_plan is None:
            raise ValueError(f"module plan {page_check.module_plan_id} not found")

        page_asset = await self._get(PageAsset, page_check.page_asset_id)
        if page_asset is None:
            raise ValueError(f"page asset {page_check.page_asset_id} not found")

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

        started_at = utcnow()
        final_url: str | None = None
        page_title: str | None = None
        page_probe: dict[str, object] | None = None
        screenshot_bytes: bytes | None = None

        await self._configure_runtime(base_url=system.base_url)
        try:
            execution_result = await self.module_executor.execute(
                steps_json=module_plan.steps_json,
                storage_state=auth_state.storage_state,
            )
            final_url = await self._read_runtime_text("get_final_url")
            page_title = await self._read_runtime_text("get_page_title")
            page_probe = await self._read_runtime_probe("probe_page")
            screenshot_bytes = await self._read_runtime_screenshot("capture_screenshot")
        finally:
            await self._close_runtime()

        execution_run.status = execution_result.status.value
        execution_run.auth_status = execution_result.auth_status.value
        execution_run.duration_ms = max(0, int((utcnow() - started_at).total_seconds() * 1000))
        failure_category = self._resolve_failure_category(execution_result=execution_result)
        execution_run.failure_category = failure_category.value if failure_category is not None else None

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
                "final_url": final_url,
                "page_title": page_title,
                "page_probe": page_probe,
            },
        )
        self.session.add(artifact)

        persisted_artifacts = [artifact]
        screenshot_artifact_ids: list[UUID] = []
        persisted_screenshot_paths: list[Path] = []
        if screenshot_bytes is not None:
            try:
                screenshot_path = self._persist_screenshot_artifact(
                    execution_run_id=execution_run.id,
                    screenshot_bytes=screenshot_bytes,
                )
            except OSError:
                screenshot_path = None

            if screenshot_path is not None:
                screenshot_artifact = ExecutionArtifact(
                    execution_run_id=execution_run.id,
                    artifact_kind="screenshot",
                    result_status=ExecutionResultStatus.SUCCESS,
                    artifact_uri=str(screenshot_path),
                    payload={
                        "mime_type": "image/png",
                        "byte_size": len(screenshot_bytes),
                        "final_url": final_url,
                        "page_title": page_title,
                        "page_probe": page_probe,
                    },
                )
                self.session.add(screenshot_artifact)
                persisted_artifacts.append(screenshot_artifact)
                screenshot_artifact_ids.append(screenshot_artifact.id)
                persisted_screenshot_paths.append(screenshot_path)

        try:
            await self._commit()
        except Exception:
            for screenshot_path in persisted_screenshot_paths:
                screenshot_path.unlink(missing_ok=True)
            raise
        await self._refresh(execution_run)
        for persisted_artifact in persisted_artifacts:
            await self._refresh(persisted_artifact)

        return RunPageCheckResult(
            page_check_id=page_check.id,
            execution_run_id=execution_run.id,
            status=execution_result.status,
            auth_status=execution_result.auth_status,
            artifact_ids=[persisted_artifact.id for persisted_artifact in persisted_artifacts],
            screenshot_artifact_ids=screenshot_artifact_ids,
            step_results=execution_result.step_results,
            failure_category=failure_category,
            final_url=final_url,
            page_title=page_title,
        )

    async def run_realtime_probe(
        self,
        *,
        execution_plan_id: UUID,
    ) -> RunPageCheckResult:
        execution_plan = await self._get(ExecutionPlan, execution_plan_id)
        if execution_plan is None:
            raise ValueError(f"execution plan {execution_plan_id} not found")
        if execution_plan.execution_track != "realtime_probe":
            raise ValueError(f"execution plan {execution_plan_id} is not realtime_probe")

        execution_request = await self._get(ExecutionRequest, execution_plan.execution_request_id)
        if execution_request is None:
            raise ValueError(f"execution request {execution_plan.execution_request_id} not found")

        if execution_plan.resolved_system_id is None:
            return await self._create_realtime_probe_resolution_failure(
                execution_plan=execution_plan,
                execution_request=execution_request,
                failure_category=FailureCategory.SYSTEM_NOT_FOUND,
                detail="system is not resolved in realtime probe execution plan",
            )

        system = await self._get(System, execution_plan.resolved_system_id)
        if system is None:
            return await self._create_realtime_probe_resolution_failure(
                execution_plan=execution_plan,
                execution_request=execution_request,
                failure_category=FailureCategory.SYSTEM_NOT_FOUND,
                detail=f"system {execution_plan.resolved_system_id} not found",
            )

        auth_state = await self._load_valid_auth_state(system_id=system.id)
        if auth_state is None or auth_state.storage_state is None:
            raise ValueError(f"valid auth state not found for system {system.id}")

        if execution_plan.resolved_page_asset_id is None:
            return await self._create_realtime_probe_resolution_failure(
                execution_plan=execution_plan,
                execution_request=execution_request,
                system_id=system.id,
                failure_category=FailureCategory.PAGE_OR_MENU_NOT_RESOLVED,
                detail="page asset is not resolved in realtime probe execution plan",
            )

        page_asset = await self._get(PageAsset, execution_plan.resolved_page_asset_id)
        if page_asset is None:
            return await self._create_realtime_probe_resolution_failure(
                execution_plan=execution_plan,
                execution_request=execution_request,
                system_id=system.id,
                failure_category=FailureCategory.PAGE_OR_MENU_NOT_RESOLVED,
                detail=f"page asset {execution_plan.resolved_page_asset_id} not found",
            )

        page = await self._get(Page, page_asset.page_id)
        if page is None:
            return await self._create_realtime_probe_resolution_failure(
                execution_plan=execution_plan,
                execution_request=execution_request,
                system_id=system.id,
                page_asset_id=page_asset.id,
                asset_version=page_asset.asset_version,
                failure_category=FailureCategory.PAGE_OR_MENU_NOT_RESOLVED,
                detail=f"page {page_asset.page_id} not found",
            )

        execution_run = ExecutionRun(
            execution_plan_id=execution_plan.id,
            status=RunnerRunStatus.RUNNING.value,
            asset_version=page_asset.asset_version,
        )
        self.session.add(execution_run)
        await self._flush()

        started_at = utcnow()
        final_url: str | None = None
        page_title: str | None = None
        page_probe: dict[str, object] | None = None
        screenshot_bytes: bytes | None = None
        probe_plan = self._build_page_probe_plan(route_path=page.route_path)

        await self._configure_runtime(base_url=system.base_url)
        try:
            execution_result = await self.module_executor.execute(
                steps_json=probe_plan.steps_json,
                storage_state=auth_state.storage_state,
            )
            final_url = await self._read_runtime_text("get_final_url")
            page_title = await self._read_runtime_text("get_page_title")
            page_probe = await self._read_runtime_probe("probe_page")
            screenshot_bytes = await self._read_runtime_screenshot("capture_screenshot")
        finally:
            await self._close_runtime()

        execution_run.status = execution_result.status.value
        execution_run.auth_status = execution_result.auth_status.value
        execution_run.duration_ms = max(0, int((utcnow() - started_at).total_seconds() * 1000))
        failure_category = self._resolve_failure_category(execution_result=execution_result)
        execution_run.failure_category = failure_category.value if failure_category is not None else None

        artifact = ExecutionArtifact(
            execution_run_id=execution_run.id,
            artifact_kind="module_execution",
            result_status=(
                ExecutionResultStatus.SUCCESS
                if execution_result.status == RunnerRunStatus.PASSED
                else ExecutionResultStatus.FAILED
            ),
            payload={
                "execution_request_id": str(execution_request.id),
                "execution_plan_id": str(execution_plan.id),
                "page_check_id": (
                    str(execution_plan.resolved_page_check_id)
                    if execution_plan.resolved_page_check_id is not None
                    else None
                ),
                "page_asset_id": str(page_asset.id),
                "system_id": str(system.id),
                "route_path": probe_plan.route_path,
                "step_results": [step.model_dump(mode="json") for step in execution_result.step_results],
                "final_url": final_url,
                "page_title": page_title,
                "page_probe": page_probe,
                "needs_recrawl": execution_plan.resolved_page_asset_id is None,
                "needs_recompile": execution_result.status == RunnerRunStatus.PASSED,
            },
        )
        self.session.add(artifact)

        persisted_artifacts = [artifact]
        screenshot_artifact_ids: list[UUID] = []
        persisted_screenshot_paths: list[Path] = []
        if screenshot_bytes is not None:
            try:
                screenshot_path = self._persist_screenshot_artifact(
                    execution_run_id=execution_run.id,
                    screenshot_bytes=screenshot_bytes,
                )
            except OSError:
                screenshot_path = None

            if screenshot_path is not None:
                screenshot_artifact = ExecutionArtifact(
                    execution_run_id=execution_run.id,
                    artifact_kind="screenshot",
                    result_status=ExecutionResultStatus.SUCCESS,
                    artifact_uri=str(screenshot_path),
                    payload={
                        "mime_type": "image/png",
                        "byte_size": len(screenshot_bytes),
                        "final_url": final_url,
                        "page_title": page_title,
                        "page_probe": page_probe,
                    },
                )
                self.session.add(screenshot_artifact)
                persisted_artifacts.append(screenshot_artifact)
                screenshot_artifact_ids.append(screenshot_artifact.id)
                persisted_screenshot_paths.append(screenshot_path)

        try:
            await self._commit()
        except Exception:
            for screenshot_path in persisted_screenshot_paths:
                screenshot_path.unlink(missing_ok=True)
            raise
        await self._refresh(execution_run)
        for persisted_artifact in persisted_artifacts:
            await self._refresh(persisted_artifact)

        return RunPageCheckResult(
            page_check_id=execution_plan.resolved_page_check_id,
            execution_run_id=execution_run.id,
            status=execution_result.status,
            auth_status=execution_result.auth_status,
            artifact_ids=[persisted_artifact.id for persisted_artifact in persisted_artifacts],
            screenshot_artifact_ids=screenshot_artifact_ids,
            step_results=execution_result.step_results,
            failure_category=failure_category,
            final_url=final_url,
            page_title=page_title,
            needs_recrawl=execution_plan.resolved_page_asset_id is None,
            needs_recompile=execution_result.status == RunnerRunStatus.PASSED,
        )

    async def _create_realtime_probe_resolution_failure(
        self,
        *,
        execution_plan: ExecutionPlan,
        execution_request: ExecutionRequest,
        failure_category: FailureCategory,
        detail: str,
        system_id: UUID | None = None,
        page_asset_id: UUID | None = None,
        asset_version: str | None = None,
    ) -> RunPageCheckResult:
        step_results = [
            StepExecutionResult(
                module="nav.menu_chain",
                status=RunnerRunStatus.FAILED,
                detail=detail,
                output={"failure_category": failure_category.value},
            )
        ]
        execution_run = ExecutionRun(
            execution_plan_id=execution_plan.id,
            status=RunnerRunStatus.FAILED.value,
            duration_ms=0,
            auth_status=AuthInjectStatus.BLOCKED.value,
            failure_category=failure_category.value,
            asset_version=asset_version,
        )
        self.session.add(execution_run)
        await self._flush()

        artifact = ExecutionArtifact(
            execution_run_id=execution_run.id,
            artifact_kind="module_execution",
            result_status=ExecutionResultStatus.FAILED,
            payload={
                "execution_request_id": str(execution_request.id),
                "execution_plan_id": str(execution_plan.id),
                "page_check_id": (
                    str(execution_plan.resolved_page_check_id)
                    if execution_plan.resolved_page_check_id is not None
                    else None
                ),
                "page_asset_id": str(page_asset_id) if page_asset_id is not None else None,
                "system_id": str(system_id) if system_id is not None else None,
                "step_results": [step.model_dump(mode="json") for step in step_results],
                "final_url": None,
                "page_title": None,
                "page_probe": None,
            },
        )
        self.session.add(artifact)
        await self._commit()
        await self._refresh(execution_run)
        await self._refresh(artifact)

        return RunPageCheckResult(
            page_check_id=execution_plan.resolved_page_check_id,
            execution_run_id=execution_run.id,
            status=RunnerRunStatus.FAILED,
            auth_status=AuthInjectStatus.BLOCKED,
            artifact_ids=[artifact.id],
            screenshot_artifact_ids=[],
            step_results=step_results,
            failure_category=failure_category,
            final_url=None,
            page_title=None,
        )

    @staticmethod
    def _build_page_probe_plan(*, route_path: str) -> PageProbePlan:
        return PageProbePlan(
            route_path=route_path,
            steps_json=[
                {
                    "module": "auth.inject_state",
                    "params": {"policy": "server_injected"},
                },
                {
                    "module": "nav.menu_chain",
                    "params": {
                        "menu_chain": [],
                        "route_path": route_path,
                    },
                },
                {
                    "module": "assert.page_open",
                    "params": {"route_path": route_path},
                },
                {
                    "module": "page.wait_ready",
                    "params": {"route_path": route_path},
                },
            ],
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

    def _resolve_failure_category(
        self,
        *,
        execution_result: ModuleExecutionResult,
    ) -> FailureCategory | None:
        if execution_result.status == RunnerRunStatus.PASSED:
            return None
        failed_step = self._first_failed_step(execution_result.step_results)
        if failed_step is not None:
            if isinstance(failed_step.output, dict):
                raw_category = failed_step.output.get("failure_category")
                if isinstance(raw_category, str) and raw_category in FailureCategory._value2member_map_:
                    return FailureCategory(raw_category)
            return _failure_category_for_module(failed_step.module)
        if execution_result.auth_status == AuthInjectStatus.BLOCKED:
            return FailureCategory.AUTH_BLOCKED
        return FailureCategory.RUNTIME_ERROR

    async def _read_runtime_text(self, method_name: str) -> str | None:
        outcome = await self._invoke_runtime_method(method_name)
        if not isinstance(outcome, str):
            return None
        normalized = outcome.strip()
        return normalized or None

    async def _read_runtime_probe(self, method_name: str) -> dict[str, object] | None:
        outcome = await self._invoke_runtime_method(method_name)
        if isinstance(outcome, dict):
            return outcome
        return None

    async def _read_runtime_screenshot(self, method_name: str) -> bytes | None:
        outcome = await self._invoke_runtime_method(method_name)
        if isinstance(outcome, (bytes, bytearray, memoryview)):
            return bytes(outcome)
        return None

    async def _invoke_runtime_method(self, method_name: str):
        method = getattr(self.runtime, method_name, None)
        if not callable(method):
            return None
        try:
            result = method()
            if inspect.isawaitable(result):
                return await result
            return result
        except Exception:
            return None

    @staticmethod
    def _first_failed_step(step_results: list[StepExecutionResult]) -> StepExecutionResult | None:
        for step in step_results:
            if step.status == RunnerRunStatus.FAILED:
                return step
        return None

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

    @staticmethod
    def _persist_screenshot_artifact(*, execution_run_id: UUID, screenshot_bytes: bytes) -> Path:
        _SCREENSHOT_ROOT.mkdir(parents=True, exist_ok=True)
        screenshot_path = _SCREENSHOT_ROOT / f"{execution_run_id}.png"
        screenshot_path.write_bytes(screenshot_bytes)
        return screenshot_path


def _failure_category_for_module(module: str) -> FailureCategory:
    if module == "nav.menu_chain":
        return FailureCategory.NAVIGATION_FAILED
    if module == "page.wait_ready":
        return FailureCategory.PAGE_NOT_READY
    if module.startswith("assert."):
        return FailureCategory.ASSERTION_FAILED
    return FailureCategory.RUNTIME_ERROR
