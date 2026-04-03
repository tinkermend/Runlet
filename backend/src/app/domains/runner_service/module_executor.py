from __future__ import annotations

from typing import Any, Protocol

from app.domains.runner_service.failure_categories import FailureCategory
from app.domains.runner_service.schemas import (
    AuthInjectStatus,
    ModuleExecutionResult,
    RunnerRunStatus,
    StepExecutionResult,
)


class RunnerRuntime(Protocol):
    async def inject_auth_state(self, *, storage_state: dict[str, object]) -> bool | str: ...

    async def navigate_menu_chain(self, *, menu_chain: list[str], route_path: str) -> bool: ...

    async def wait_page_ready(self, *, route_path: str) -> bool: ...

    async def assert_table_visible(self, *, route_path: str | None = None) -> bool: ...

    async def assert_page_open(self, *, route_path: str) -> bool: ...

    async def open_create_modal(self) -> bool: ...

    async def capture_screenshot(self) -> bytes: ...

    async def get_final_url(self) -> str | None: ...

    async def get_page_title(self) -> str | None: ...

    async def probe_page(self) -> dict[str, object] | None: ...


class ModuleExecutor:
    def __init__(self, *, runtime: RunnerRuntime) -> None:
        self.runtime = runtime

    async def execute(
        self,
        *,
        steps_json: list[dict[str, object]],
        storage_state: dict[str, object],
    ) -> ModuleExecutionResult:
        auth_status = AuthInjectStatus.BLOCKED
        step_results: list[StepExecutionResult] = []

        for raw_step in steps_json:
            module = str(raw_step.get("module") or "")
            params = _coerce_params(raw_step.get("params"))
            try:
                if module == "auth.inject_state":
                    auth_status = await self._inject_auth_state(storage_state=storage_state)
                    step_status = (
                        RunnerRunStatus.PASSED
                        if auth_status != AuthInjectStatus.BLOCKED
                        else RunnerRunStatus.FAILED
                    )
                    output: dict[str, object] = {"auth_status": auth_status.value}
                    if auth_status == AuthInjectStatus.BLOCKED:
                        output["failure_category"] = FailureCategory.AUTH_BLOCKED.value
                    step_results.append(
                        StepExecutionResult(
                            module=module,
                            status=step_status,
                            output=output,
                        )
                    )
                    if auth_status == AuthInjectStatus.BLOCKED:
                        return ModuleExecutionResult(
                            status=RunnerRunStatus.FAILED,
                            auth_status=auth_status,
                            step_results=step_results,
                        )
                elif module == "nav.menu_chain":
                    await self._expect_truthy(
                        module=module,
                        outcome=await self.runtime.navigate_menu_chain(
                            menu_chain=_coerce_menu_chain(params.get("menu_chain")),
                            route_path=str(params.get("route_path") or ""),
                        ),
                    )
                    step_results.append(
                        StepExecutionResult(
                            module=module,
                            status=RunnerRunStatus.PASSED,
                            output={
                                "menu_chain": _coerce_menu_chain(params.get("menu_chain")),
                                "route_path": str(params.get("route_path") or ""),
                            },
                        )
                    )
                elif module == "page.wait_ready":
                    route_path = str(params.get("route_path") or "")
                    await self._expect_truthy(
                        module=module,
                        outcome=await self.runtime.wait_page_ready(route_path=route_path),
                    )
                    step_results.append(
                        StepExecutionResult(
                            module=module,
                            status=RunnerRunStatus.PASSED,
                            output={"route_path": route_path},
                        )
                    )
                elif module == "assert.table_visible":
                    route_path = _optional_text(params.get("route_path"))
                    await self._expect_truthy(
                        module=module,
                        outcome=await self.runtime.assert_table_visible(route_path=route_path),
                    )
                    step_results.append(
                        StepExecutionResult(
                            module=module,
                            status=RunnerRunStatus.PASSED,
                            output={"route_path": route_path} if route_path else None,
                        )
                    )
                elif module in {"assert.page_open", "assert.page_ready"}:
                    route_path = str(params.get("route_path") or "")
                    await self._expect_truthy(
                        module=module,
                        outcome=await self.runtime.assert_page_open(route_path=route_path),
                    )
                    step_results.append(
                        StepExecutionResult(
                            module=module,
                            status=RunnerRunStatus.PASSED,
                            output={"route_path": route_path},
                        )
                    )
                elif module == "action.open_create_modal":
                    await self._expect_truthy(
                        module=module,
                        outcome=await self.runtime.open_create_modal(),
                    )
                    step_results.append(
                        StepExecutionResult(
                            module=module,
                            status=RunnerRunStatus.PASSED,
                        )
                    )
                else:
                    raise ValueError(f"unsupported module: {module}")
            except Exception as exc:
                failure_category = _failure_category_for_module(module)
                step_results.append(
                    StepExecutionResult(
                        module=module,
                        status=RunnerRunStatus.FAILED,
                        detail=str(exc),
                        output={"failure_category": failure_category.value},
                    )
                )
                return ModuleExecutionResult(
                    status=RunnerRunStatus.FAILED,
                    auth_status=auth_status,
                    step_results=step_results,
                )

        return ModuleExecutionResult(
            status=RunnerRunStatus.PASSED,
            auth_status=auth_status,
            step_results=step_results,
        )

    async def _inject_auth_state(self, *, storage_state: dict[str, object]) -> AuthInjectStatus:
        outcome = await self.runtime.inject_auth_state(storage_state=storage_state)
        if outcome is True:
            return AuthInjectStatus.REUSED
        if outcome is False:
            return AuthInjectStatus.BLOCKED
        normalized = str(outcome or "").strip().lower()
        if normalized in {"reused", "refreshed", "blocked"}:
            return AuthInjectStatus(normalized)
        raise ValueError(f"unsupported auth inject outcome: {outcome}")

    async def _expect_truthy(self, *, module: str, outcome: Any) -> None:
        if outcome:
            return
        raise ValueError(f"module {module} returned falsy result")


def _coerce_params(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    return {}


def _coerce_menu_chain(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _failure_category_for_module(module: str) -> FailureCategory:
    if module == "nav.menu_chain":
        return FailureCategory.NAVIGATION_FAILED
    if module == "page.wait_ready":
        return FailureCategory.PAGE_NOT_READY
    if module.startswith("assert."):
        return FailureCategory.ASSERTION_FAILED
    return FailureCategory.RUNTIME_ERROR
