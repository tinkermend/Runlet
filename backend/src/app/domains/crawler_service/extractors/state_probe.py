from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Protocol

from app.domains.crawler_service.schemas import (
    ALLOWED_STATE_PROBE_ACTIONS,
    CrawlExtractionResult,
    ElementCandidate,
)


class StateProbeExtractor(Protocol):
    async def extract(
        self,
        *,
        browser_session,
        system,
        crawl_scope: str,
    ) -> CrawlExtractionResult: ...


class ControlledStateProbeExtractor:
    ALLOWED_ACTIONS = ALLOWED_STATE_PROBE_ACTIONS
    _KEY_ACTION_CONTEXT_FIELDS = (
        "active_tab",
        "modal_title",
        "drawer_title",
        "view_mode",
        "panel_title",
        "tree_node",
    )

    def __init__(self, *, max_actions_per_page: int = 6) -> None:
        self.max_actions_per_page = max(1, max_actions_per_page)

    async def extract(
        self,
        *,
        browser_session,
        system,
        crawl_scope: str,
    ) -> CrawlExtractionResult:
        del system
        warnings: list[str] = []
        elements: list[ElementCandidate] = []
        visited_signatures: set[str] = set()
        actions_consumed: dict[str, int] = defaultdict(int)

        try:
            baseline_states = await self._collect_baseline_states(
                browser_session=browser_session,
                crawl_scope=crawl_scope,
            )
        except Exception:
            baseline_states = []
            self._append_warning(warnings, "state_probe_baseline_degraded")
        for baseline_state in baseline_states:
            self._collect_state_elements(
                state=baseline_state,
                elements=elements,
                warnings=warnings,
                visited_signatures=visited_signatures,
            )

        try:
            actions = await self._collect_actions(browser_session=browser_session, crawl_scope=crawl_scope)
        except Exception:
            actions = []
            self._append_warning(warnings, "state_probe_actions_degraded")
        for action in actions:
            route_path = self._normalize_route_path(action.get("route_path") or action.get("page_route_path"))
            if route_path is None:
                continue

            entry_type = self._normalize_entry_type(action.get("entry_type") or action.get("interaction_type"))
            if entry_type is None or entry_type not in self.ALLOWED_ACTIONS:
                self._append_warning(warnings, "unsafe_action_rejected")
                continue

            if self._is_permission_blocked(action):
                self._append_warning(warnings, "blocked_by_permission")
                continue

            if actions_consumed[route_path] >= self.max_actions_per_page:
                self._append_warning(warnings, "interaction_budget_exhausted")
                continue

            actions_consumed[route_path] += 1
            try:
                state_payload = await self._perform_action(
                    browser_session=browser_session,
                    action=action,
                    crawl_scope=crawl_scope,
                )
            except PermissionError:
                self._append_warning(warnings, "blocked_by_permission")
                continue
            except Exception:
                self._append_warning(warnings, "unsafe_action_rejected")
                continue

            state = self._to_state_payload(default_route=route_path, action=action, payload=state_payload)
            self._collect_state_elements(
                state=state,
                elements=elements,
                warnings=warnings,
                visited_signatures=visited_signatures,
            )

        quality_score = min(1.0, 0.35 + (0.06 * len(visited_signatures)) + (0.03 * len(elements)))
        return CrawlExtractionResult(
            framework_detected=self._clean_text(getattr(browser_session, "framework_hint", None)),
            quality_score=quality_score if elements else 0.0,
            elements=elements,
            failure_reason=None,
            warning_messages=warnings,
            degraded=False,
        )

    def _collect_state_elements(
        self,
        *,
        state: dict[str, object],
        elements: list[ElementCandidate],
        warnings: list[str],
        visited_signatures: set[str],
    ) -> None:
        route_path = self._normalize_route_path(state.get("route_path"))
        if route_path is None:
            return
        state_context = self._to_state_context(state.get("state_context"))
        state_signature = build_state_signature(route_path, state_context)
        if state_signature in visited_signatures:
            self._append_warning(warnings, "state_signature_duplicate")
            return

        raw_elements = state.get("elements")
        if not isinstance(raw_elements, list) or not raw_elements:
            return

        state_elements: list[ElementCandidate] = []
        for raw_element in raw_elements:
            if not isinstance(raw_element, dict):
                continue
            candidate = self._to_element_candidate(
                route_path=route_path,
                state_signature=state_signature,
                state_context=state_context,
                raw_element=raw_element,
            )
            if candidate is None:
                continue
            state_elements.append(candidate)

        if not state_elements:
            return

        visited_signatures.add(state_signature)
        elements.extend(state_elements)

    def _to_element_candidate(
        self,
        *,
        route_path: str,
        state_signature: str,
        state_context: dict[str, object],
        raw_element: dict[str, object],
    ) -> ElementCandidate | None:
        element_type = self._clean_text(raw_element.get("element_type") or raw_element.get("tag_name"))
        if element_type is None:
            return None
        element_role = self._clean_text(raw_element.get("role") or raw_element.get("element_role"))
        element_text = self._clean_text(raw_element.get("text") or raw_element.get("element_text"))
        locator_candidates = self._normalize_locator_candidates(raw_element.get("locator_candidates"))
        playwright_locator = self._clean_text(
            raw_element.get("playwright_locator")
            or raw_element.get("locator")
            or (locator_candidates[0].get("selector") if locator_candidates else None)
        )
        if playwright_locator is None:
            playwright_locator = self._build_locator(
                role=element_role,
                text=element_text,
                fallback_tag=element_type,
            )
        if not locator_candidates and playwright_locator:
            strategy_type = "semantic" if element_role and element_text else "css"
            locator_candidates = [{"strategy_type": strategy_type, "selector": playwright_locator}]
        attributes = raw_element.get("attributes") if isinstance(raw_element.get("attributes"), dict) else None
        usage_description = self._clean_text(raw_element.get("usage_description"))

        return ElementCandidate(
            page_route_path=route_path,
            element_type=element_type,
            state_signature=state_signature,
            state_context=state_context or None,
            locator_candidates=locator_candidates,
            element_role=element_role,
            element_text=element_text,
            attributes=attributes,
            playwright_locator=playwright_locator,
            usage_description=usage_description,
        )

    async def _collect_baseline_states(self, *, browser_session, crawl_scope: str) -> list[dict[str, object]]:
        collector = getattr(browser_session, "collect_state_probe_baseline", None)
        if callable(collector):
            return self._ensure_dict_list(await collector(crawl_scope=crawl_scope))

        element_collector = getattr(browser_session, "collect_dom_elements", None)
        if not callable(element_collector):
            return []

        raw_elements = self._ensure_dict_list(await element_collector(crawl_scope=crawl_scope))
        grouped_elements: dict[str, list[dict[str, object]]] = defaultdict(list)
        for element in raw_elements:
            route_path = self._normalize_route_path(element.get("page_route_path") or element.get("route_path"))
            if route_path is None:
                continue
            grouped_elements[route_path].append(element)

        states: list[dict[str, object]] = []
        for route_path, items in grouped_elements.items():
            states.append(
                {
                    "route_path": route_path,
                    "state_context": {"active_tab": "default"},
                    "elements": items,
                }
            )
        return states

    async def _collect_actions(self, *, browser_session, crawl_scope: str) -> list[dict[str, object]]:
        collector = getattr(browser_session, "collect_state_probe_actions", None)
        if callable(collector):
            return self._ensure_dict_list(await collector(crawl_scope=crawl_scope))
        return self._ensure_dict_list(getattr(browser_session, "state_probe_actions", []))

    async def _perform_action(
        self,
        *,
        browser_session,
        action: dict[str, object],
        crawl_scope: str,
    ) -> dict[str, object]:
        executor = getattr(browser_session, "perform_state_probe_action", None)
        if callable(executor):
            payload = await executor(action=action, crawl_scope=crawl_scope)
            if isinstance(payload, dict):
                return payload
            return {}
        return action

    def _to_state_payload(
        self,
        *,
        default_route: str,
        action: dict[str, object],
        payload: dict[str, object],
    ) -> dict[str, object]:
        merged: dict[str, object] = {}
        merged.update(action)
        merged.update(payload)

        route_path = self._normalize_route_path(
            merged.get("route_path") or merged.get("page_route_path") or default_route
        )
        merged["route_path"] = route_path or default_route

        state_context = self._to_state_context(merged.get("state_context"))
        if not state_context:
            for key in self._KEY_ACTION_CONTEXT_FIELDS:
                value = self._clean_text(merged.get(key))
                if value is not None:
                    state_context[key] = value
            for numeric_key in ("page_number", "page_index", "page", "tree_level"):
                numeric_value = merged.get(numeric_key)
                if isinstance(numeric_value, (int, float)) and not isinstance(numeric_value, bool):
                    state_context[numeric_key] = int(numeric_value) if float(numeric_value).is_integer() else numeric_value
        merged["state_context"] = state_context
        merged["elements"] = self._ensure_dict_list(merged.get("elements"))
        return merged

    def _normalize_locator_candidates(self, value: object) -> list[dict[str, object]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, object]] = []
        seen: set[str] = set()
        for candidate in value:
            if not isinstance(candidate, dict):
                continue
            strategy_type = self._clean_text(candidate.get("strategy_type"))
            selector = self._clean_text(candidate.get("selector"))
            if strategy_type is None or selector is None:
                continue
            key = json.dumps(
                {"strategy_type": strategy_type, "selector": selector},
                ensure_ascii=False,
                sort_keys=True,
            )
            if key in seen:
                continue
            seen.add(key)
            normalized.append({"strategy_type": strategy_type, "selector": selector})
        return normalized

    def _build_locator(self, *, role: str | None, text: str | None, fallback_tag: str) -> str:
        if role and text:
            return f"role={role}[name='{self._escape_quote(text)}']"
        if text:
            return f"text='{self._escape_quote(text)}'"
        return f"css={fallback_tag}"

    def _to_state_context(self, value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            return {}
        state_context: dict[str, object] = {}
        for key, raw in value.items():
            clean_key = self._clean_text(key)
            if clean_key is None:
                continue
            if isinstance(raw, (str, int, float, bool)):
                if isinstance(raw, str):
                    cleaned = raw.strip()
                    if not cleaned:
                        continue
                    state_context[clean_key] = cleaned
                else:
                    state_context[clean_key] = raw
        return state_context

    def _is_permission_blocked(self, action: dict[str, object]) -> bool:
        blocked = action.get("blocked_by_permission")
        if isinstance(blocked, bool):
            return blocked
        permission_result = self._clean_text(action.get("permission_result"))
        if permission_result is None:
            return False
        return permission_result.lower() in {"blocked", "denied", "forbidden"}

    def _ensure_dict_list(self, value: object) -> list[dict[str, object]]:
        if not isinstance(value, list):
            return []
        items: list[dict[str, object]] = []
        for item in value:
            if isinstance(item, dict):
                items.append(dict(item))
        return items

    def _normalize_route_path(self, value: object) -> str | None:
        if not isinstance(value, str):
            return None
        route_path = value.strip()
        if not route_path or not route_path.startswith("/"):
            return None
        return route_path.rstrip("/") or "/"

    def _normalize_entry_type(self, value: object) -> str | None:
        clean_value = self._clean_text(value)
        if clean_value is None:
            return None
        return clean_value.lower().replace("-", "_")

    def _append_warning(self, warnings: list[str], reason: str) -> None:
        if reason not in warnings:
            warnings.append(reason)

    def _escape_quote(self, value: str) -> str:
        return value.replace("'", "\\'")

    def _clean_text(self, value: object) -> str | None:
        if not isinstance(value, str):
            return None
        cleaned = value.strip()
        return cleaned or None


def build_state_signature(route_path: str, state_context: dict[str, object]) -> str:
    normalized_route = route_path.strip()
    if not normalized_route.startswith("/"):
        normalized_route = f"/{normalized_route.lstrip('/')}"
    route_segment = normalized_route.strip("/").replace("/", ":") or "root"

    suffixes: list[str] = []
    consumed_keys: set[str] = set()
    active_tab = _normalize_signature_value(state_context.get("active_tab"))
    if active_tab is not None:
        consumed_keys.add("active_tab")
        if active_tab == "default":
            suffixes.append("default")
        else:
            suffixes.append(f"tab={active_tab}")

    modal_title = _normalize_signature_value(state_context.get("modal_title"))
    if modal_title is not None:
        consumed_keys.add("modal_title")
        suffixes.append(f"modal={modal_title}")

    drawer_title = _normalize_signature_value(state_context.get("drawer_title"))
    if drawer_title is not None:
        consumed_keys.add("drawer_title")
        suffixes.append(f"drawer={drawer_title}")

    view_mode = _normalize_signature_value(state_context.get("view_mode"))
    if view_mode is not None:
        consumed_keys.add("view_mode")
        suffixes.append(f"view={view_mode}")

    panel_title = _normalize_signature_value(state_context.get("panel_title"))
    if panel_title is not None:
        consumed_keys.add("panel_title")
        suffixes.append(f"panel={panel_title}")

    tree_node = _normalize_signature_value(state_context.get("tree_node"))
    if tree_node is not None:
        consumed_keys.add("tree_node")
        suffixes.append(f"tree={tree_node}")

    extra_fields: list[str] = []
    for key in sorted(state_context):
        if key in consumed_keys:
            continue
        normalized_value = _normalize_signature_value(state_context.get(key))
        if normalized_value is None:
            continue
        normalized_key = key.strip().lower().replace("-", "_").replace(" ", "_")
        if not normalized_key:
            continue
        extra_fields.append(f"{normalized_key}={normalized_value}")
    suffixes.extend(extra_fields)

    if not suffixes:
        suffixes.append("default")
    return ":".join([route_segment, *suffixes])


def _normalize_signature_value(value: object) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return format(value, "g")
    if isinstance(value, str):
        normalized = value.strip().lower().replace(" ", "_")
        return normalized or None
    return None
