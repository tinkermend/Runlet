from __future__ import annotations

from dataclasses import dataclass
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

    async def enter_state(self, *, state_signature: str) -> bool: ...

    async def resolve_locator_bundle(
        self,
        *,
        locator_bundle: dict[str, object],
        context_constraints: dict[str, object] | None = None,
    ) -> dict[str, object]: ...

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
                elif module == "state.enter":
                    state_signature = str(params.get("state_signature") or "")
                    try:
                        reached = await self.runtime.enter_state(state_signature=state_signature)
                    except Exception as exc:
                        detail = str(exc).strip() or "state_not_reached"
                        step_results.append(
                            StepExecutionResult(
                                module=module,
                                status=RunnerRunStatus.FAILED,
                                detail=detail,
                                output={
                                    "state_signature": state_signature,
                                    "failure_category": "state_not_reached",
                                },
                            )
                        )
                        return ModuleExecutionResult(
                            status=RunnerRunStatus.FAILED,
                            auth_status=auth_status,
                            step_results=step_results,
                        )
                    if not reached:
                        step_results.append(
                            StepExecutionResult(
                                module=module,
                                status=RunnerRunStatus.FAILED,
                                detail=f"state_not_reached: state signature {state_signature} was not reached",
                                output={
                                    "state_signature": state_signature,
                                    "failure_category": "state_not_reached",
                                },
                            )
                        )
                        return ModuleExecutionResult(
                            status=RunnerRunStatus.FAILED,
                            auth_status=auth_status,
                            step_results=step_results,
                        )
                    step_results.append(
                        StepExecutionResult(
                            module=module,
                            status=RunnerRunStatus.PASSED,
                            output={"state_signature": state_signature},
                        )
                    )
                elif module == "locator.assert":
                    locator_bundle = _coerce_params(params.get("locator_bundle"))
                    context_constraints = _coerce_optional_dict(params.get("context_constraints"))
                    locator_match = _coerce_locator_match(
                        await self.runtime.resolve_locator_bundle(
                            locator_bundle=locator_bundle,
                            context_constraints=context_constraints,
                        )
                    )
                    output = _build_locator_output(
                        assertion=_optional_text(params.get("assertion")),
                        expected_element_type=_optional_text(params.get("expected_element_type")),
                        locator_match=locator_match,
                    )
                    if not locator_match.matched:
                        step_results.append(
                            StepExecutionResult(
                                module=module,
                                status=RunnerRunStatus.FAILED,
                                detail=f"locator assert failed: {locator_match.failure_category}",
                                output=output,
                            )
                        )
                        return ModuleExecutionResult(
                            status=RunnerRunStatus.FAILED,
                            auth_status=auth_status,
                            step_results=step_results,
                        )
                    step_results.append(
                        StepExecutionResult(
                            module=module,
                            status=RunnerRunStatus.PASSED,
                            output=output,
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


def _coerce_optional_dict(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return value
    return None


@dataclass(slots=True)
class _LocatorMatch:
    matched: bool
    matched_rank: int | None
    strategy_type: str | None
    failure_category: str
    context_mismatch: bool
    ambiguous_match: bool


def _coerce_locator_match(value: object) -> _LocatorMatch:
    payload = value if isinstance(value, dict) else {}
    matched = bool(payload.get("matched"))
    matched_rank = _coerce_positive_int(payload.get("matched_rank"))
    strategy_type = _optional_text(payload.get("strategy_type"))
    failure_category = _optional_text(payload.get("failure_category"))
    context_mismatch = bool(payload.get("context_mismatch"))
    ambiguous_match = bool(payload.get("ambiguous_match"))
    if matched:
        return _LocatorMatch(
            matched=True,
            matched_rank=matched_rank or 1,
            strategy_type=strategy_type,
            failure_category="",
            context_mismatch=context_mismatch,
            ambiguous_match=ambiguous_match,
        )
    return _LocatorMatch(
        matched=False,
        matched_rank=None,
        strategy_type=None,
        failure_category=failure_category or "locator_all_failed",
        context_mismatch=context_mismatch,
        ambiguous_match=ambiguous_match,
    )


def _coerce_positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


def _build_locator_output(
    *,
    assertion: str | None,
    expected_element_type: str | None,
    locator_match: _LocatorMatch,
) -> dict[str, object]:
    output: dict[str, object] = {
        "matched_rank": locator_match.matched_rank,
        "strategy_type": locator_match.strategy_type,
        "failure_category": None if locator_match.matched else locator_match.failure_category,
    }
    if assertion:
        output["assertion"] = assertion
    if expected_element_type:
        output["expected_element_type"] = expected_element_type
    if locator_match.context_mismatch:
        output["context_mismatch"] = True
    if locator_match.ambiguous_match:
        output["ambiguous_match"] = True
    return output


def _failure_category_for_module(module: str) -> FailureCategory:
    if module == "nav.menu_chain":
        return FailureCategory.NAVIGATION_FAILED
    if module == "page.wait_ready":
        return FailureCategory.PAGE_NOT_READY
    if module == "locator.assert":
        return FailureCategory.ASSERTION_FAILED
    if module.startswith("assert."):
        return FailureCategory.ASSERTION_FAILED
    return FailureCategory.RUNTIME_ERROR
