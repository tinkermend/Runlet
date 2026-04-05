from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Protocol

from app.domains.crawler_service.extractors.page_discovery import build_page_visit_targets
from app.domains.crawler_service.navigation_targets import NavigationTarget, NavigationTargetRegistry
from app.domains.crawler_service.schemas import (
    ALLOWED_STATE_PROBE_ACTIONS,
    CrawlExtractionResult,
    ElementCandidate,
    NavigationTargetResult,
    PageCandidate,
)


class StateProbeExtractor(Protocol):
    async def extract(
        self,
        *,
        browser_session,
        system,
        crawl_scope: str,
        page_candidates: list[PageCandidate] | None = None,
        navigation_targets: list[NavigationTargetResult | dict[str, object]] | None = None,
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
        page_candidates: list[PageCandidate] | None = None,
        navigation_targets: list[NavigationTargetResult | dict[str, object]] | None = None,
    ) -> CrawlExtractionResult:
        del system
        page_visit_targets = build_page_visit_targets(
            pages=page_candidates or [],
            navigation_targets=navigation_targets or [],
        )
        if page_visit_targets and callable(getattr(browser_session, "visit_page_target", None)):
            return await self._extract_page_visit_first(
                browser_session=browser_session,
                crawl_scope=crawl_scope,
                page_visit_targets=page_visit_targets,
                navigation_targets=navigation_targets or [],
            )

        return await self._extract_legacy(
            browser_session=browser_session,
            crawl_scope=crawl_scope,
        )

    async def _extract_legacy(
        self,
        *,
        browser_session,
        crawl_scope: str,
    ) -> CrawlExtractionResult:
        warnings: list[str] = []
        elements: list[ElementCandidate] = []
        visited_signatures: set[str] = set()
        navigation_targets: list[NavigationTarget] = []
        registry = NavigationTargetRegistry(
            max_targets_per_route=self.max_actions_per_page,
            max_total_targets=max(8, self.max_actions_per_page * 8),
            max_targets_per_kind=max(4, self.max_actions_per_page * 4),
            max_children_per_parent=max(4, self.max_actions_per_page * 4),
        )

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
                navigation_targets.append(
                    self._build_navigation_target(
                        action=action,
                        route_path=route_path,
                        target_kind=entry_type,
                        status="blocked",
                        reason="blocked_by_permission",
                    )
                )
                self._append_warning(warnings, "blocked_by_permission")
                continue

            target = self._build_navigation_target(action=action, route_path=route_path, target_kind=entry_type)
            decision = registry.add(target)
            if not decision.accepted:
                navigation_targets.append(target)
                if decision.reason == "duplicate_target":
                    self._append_warning(warnings, "navigation_target_duplicate")
                elif decision.reason and decision.reason.endswith("budget_exhausted"):
                    self._append_warning(warnings, "interaction_budget_exhausted")
                    self._append_warning(warnings, decision.reason)
                continue

            try:
                state_payload = await self._perform_action(
                    browser_session=browser_session,
                    action=action,
                    crawl_scope=crawl_scope,
                )
            except PermissionError:
                target.mark_blocked("blocked_by_permission")
                navigation_targets.append(target)
                self._append_warning(warnings, "blocked_by_permission")
                continue
            except Exception:
                target.mark_blocked("unsafe_action_rejected")
                navigation_targets.append(target)
                self._append_warning(warnings, "unsafe_action_rejected")
                continue

            if not self._action_payload_applied(state_payload):
                target.mark_not_applied(
                    "state_transition_not_applied",
                    detail=self._action_payload_rejection_reason(state_payload),
                )
                navigation_targets.append(target)
                self._append_warning(warnings, "state_transition_not_applied")
                continue

            target.mark_applied()
            navigation_targets.append(target)
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
            navigation_targets=[NavigationTargetResult.model_validate(target.to_record()) for target in navigation_targets],
            failure_reason=None,
            warning_messages=warnings,
            degraded=False,
        )

    async def _extract_page_visit_first(
        self,
        *,
        browser_session,
        crawl_scope: str,
        page_visit_targets: list[NavigationTarget],
        navigation_targets: list[NavigationTargetResult | dict[str, object]],
    ) -> CrawlExtractionResult:
        warnings: list[str] = []
        elements: list[ElementCandidate] = []
        visited_signatures: set[str] = set()
        registry = NavigationTargetRegistry(
            max_targets_per_route=self.max_actions_per_page,
            max_total_targets=max(8, self.max_actions_per_page * 8),
            max_targets_per_kind=max(4, self.max_actions_per_page * 4),
            max_children_per_parent=max(4, self.max_actions_per_page * 4),
        )

        for page_target in page_visit_targets:
            try:
                page_context = await self._visit_page_target(
                    browser_session=browser_session,
                    page_target=page_target,
                    crawl_scope=crawl_scope,
                )
            except Exception:
                self._append_warning(warnings, "state_probe_baseline_degraded")
                continue

            self._append_warnings(
                warnings=warnings,
                reasons=page_context.get("warning_messages"),
            )
            baseline_state = self._to_page_context_state(page_context=page_context, default_route=page_target.route_hint)
            self._collect_state_elements(
                state=baseline_state,
                elements=elements,
                warnings=warnings,
                visited_signatures=visited_signatures,
            )

            page_state_targets = self._build_state_targets_for_page(
                page_context=page_context,
                navigation_targets=navigation_targets,
            )
            for target in page_state_targets:
                decision = registry.add(target)
                if not decision.accepted:
                    if decision.reason == "duplicate_target":
                        self._append_warning(warnings, "navigation_target_duplicate")
                    elif decision.reason and decision.reason.endswith("budget_exhausted"):
                        self._append_warning(warnings, "interaction_budget_exhausted")
                        self._append_warning(warnings, decision.reason)
                    continue

                action = build_navigation_action_payload(
                    target=target,
                    route_path=target.route_hint,
                    base_state_context=baseline_state.get("state_context"),
                )

                try:
                    state_payload = await self._perform_navigation_target(
                        browser_session=browser_session,
                        target=action,
                        page_context=page_context,
                        crawl_scope=crawl_scope,
                    )
                except PermissionError:
                    target.mark_blocked("blocked_by_permission")
                    self._append_warning(warnings, "blocked_by_permission")
                    continue
                except Exception:
                    target.mark_blocked("unsafe_action_rejected")
                    self._append_warning(warnings, "unsafe_action_rejected")
                    continue

                if not self._action_payload_applied(state_payload):
                    detail = self._action_payload_rejection_reason(state_payload)
                    target.mark_not_applied("state_transition_not_applied", detail=detail)
                    self._append_warning(warnings, "state_transition_not_applied")
                    if detail not in {"state_transition_not_applied", "blocked_by_permission", "unsafe_action_rejected"}:
                        self._append_warning(warnings, detail)
                    continue

                target.mark_applied()
                state = self._to_state_payload(
                    default_route=page_target.route_hint or page_context.get("route_path") or "/",
                    action=action,
                    payload=state_payload,
                    page_context=page_context,
                )
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
            navigation_targets=self._serialize_registry_targets(registry=registry),
            failure_reason=None,
            warning_messages=warnings,
            degraded=False,
        )

    def _build_navigation_target(
        self,
        *,
        action: dict[str, object],
        route_path: str,
        target_kind: str,
        status: str = "discovered",
        reason: str | None = None,
    ) -> NavigationTarget:
        target = NavigationTarget(
            target_kind=target_kind,
            route_hint=route_path,
            locator_candidates=self._normalize_locator_candidates(action.get("locator_candidates")),
            state_context=self._to_state_context(action.get("state_context")),
            parent_target_key=f"page:{route_path}",
            discovery_source="state_probe_action",
            materialization_status=status,
            rejection_reason=reason,
        )
        if status == "blocked" and reason is not None:
            target.mark_blocked(reason)
        elif status == "not_applied" and reason is not None:
            target.mark_not_applied(reason)
        return target

    async def _visit_page_target(
        self,
        *,
        browser_session,
        page_target: NavigationTarget,
        crawl_scope: str,
    ) -> dict[str, object]:
        visitor = getattr(browser_session, "visit_page_target", None)
        if callable(visitor):
            payload = await visitor(page_target=page_target.to_record(), crawl_scope=crawl_scope)
            if isinstance(payload, dict):
                return payload
        return {
            "route_path": page_target.route_hint,
            "resolved_route": page_target.route_hint,
            "state_context": {"active_tab": "default"},
            "elements": [],
        }

    async def _perform_navigation_target(
        self,
        *,
        browser_session,
        target: dict[str, object],
        page_context: dict[str, object],
        crawl_scope: str,
    ) -> dict[str, object]:
        executor = getattr(browser_session, "perform_navigation_target", None)
        if callable(executor):
            payload = await executor(target=target, page_context=page_context, crawl_scope=crawl_scope)
            if isinstance(payload, dict):
                return payload
            return {}
        return await self._perform_action(browser_session=browser_session, action=target, crawl_scope=crawl_scope)

    def _build_state_targets_for_page(
        self,
        *,
        page_context: dict[str, object],
        navigation_targets: list[NavigationTargetResult | dict[str, object]],
    ) -> list[NavigationTarget]:
        route_path = self._normalize_route_path(page_context.get("resolved_route") or page_context.get("route_path"))
        if route_path is None:
            return []

        targets: list[NavigationTarget] = []
        targets.extend(
            self._normalize_discovered_state_targets(
                route_path=route_path,
                navigation_targets=navigation_targets,
            )
        )
        targets.extend(self._derive_state_targets_from_page_context(page_context=page_context, route_path=route_path))
        return targets

    def _normalize_discovered_state_targets(
        self,
        *,
        route_path: str,
        navigation_targets: list[NavigationTargetResult | dict[str, object]],
    ) -> list[NavigationTarget]:
        normalized: list[NavigationTarget] = []
        page_parent_key = f"page:{route_path}"
        for raw_target in navigation_targets:
            record = raw_target if isinstance(raw_target, dict) else raw_target.model_dump()
            target_kind = self._normalize_entry_type(record.get("target_kind"))
            if target_kind is None or target_kind == "page_route":
                continue
            target_route = self._normalize_route_path(record.get("route_hint") or record.get("route_path"))
            parent_target_key = self._clean_text(record.get("parent_target_key"))
            if target_route != route_path and parent_target_key != page_parent_key:
                continue
            normalized.append(
                NavigationTarget(
                    target_kind=target_kind,
                    route_hint=route_path,
                    locator_candidates=self._normalize_locator_candidates(record.get("locator_candidates")),
                    state_context=self._to_state_context(record.get("state_context")),
                    parent_target_key=page_parent_key,
                    discovery_source=self._clean_text(record.get("discovery_source")) or "page_discovery",
                    metadata=record.get("metadata") if isinstance(record.get("metadata"), dict) else {},
                )
            )
        return normalized

    def _derive_state_targets_from_page_context(
        self,
        *,
        page_context: dict[str, object],
        route_path: str,
    ) -> list[NavigationTarget]:
        targets: list[NavigationTarget] = []
        raw_elements = self._ensure_dict_list(page_context.get("elements"))
        for raw_element in raw_elements:
            entry_type = self._infer_entry_type_from_element(raw_element)
            if entry_type is None or entry_type not in self.ALLOWED_ACTIONS:
                continue
            state_context = self._infer_state_context_from_element(entry_type=entry_type, raw_element=raw_element)
            if not state_context:
                continue
            targets.append(
                NavigationTarget(
                    target_kind=entry_type,
                    route_hint=route_path,
                    locator_candidates=self._normalize_locator_candidates(raw_element.get("locator_candidates")),
                    state_context=state_context,
                    parent_target_key=f"page:{route_path}",
                    discovery_source="page_context",
                )
            )
        return targets

    def _infer_entry_type_from_element(self, raw_element: dict[str, object]) -> str | None:
        role = self._clean_text(raw_element.get("role") or raw_element.get("element_role"))
        element_type = self._clean_text(raw_element.get("element_type") or raw_element.get("tag_name"))
        text = self._clean_text(raw_element.get("text") or raw_element.get("element_text")) or ""
        lower_text = text.lower()

        if role == "tab" and text:
            return "tab_switch"
        if element_type == "button" and any(keyword in lower_text for keyword in ("新增", "新建", "创建", "添加", "add", "new", "create")):
            return "open_modal"
        if text.isdigit():
            return "paginate_probe"
        if element_type == "button" and any(
            keyword in lower_text for keyword in ("列表", "卡片", "视图", "table", "grid", "list", "card")
        ):
            return "toggle_view"
        return None

    def _infer_state_context_from_element(
        self,
        *,
        entry_type: str,
        raw_element: dict[str, object],
    ) -> dict[str, object]:
        label = self._clean_text(raw_element.get("text") or raw_element.get("element_text"))
        if label is None:
            return {}
        if entry_type == "tab_switch":
            return {"active_tab": label}
        if entry_type == "open_modal":
            return {"modal_title": label}
        if entry_type == "paginate_probe" and label.isdigit():
            return {"page_number": int(label)}
        if entry_type == "toggle_view":
            return {"view_mode": label}
        return {}

    def _to_page_context_state(
        self,
        *,
        page_context: dict[str, object],
        default_route: str | None,
    ) -> dict[str, object]:
        route_path = self._normalize_route_path(
            page_context.get("resolved_route") or page_context.get("route_path") or default_route
        )
        return {
            "route_path": route_path or default_route or "/",
            "state_context": merge_state_context({"active_tab": "default"}, page_context.get("state_context")),
            "elements": self._ensure_dict_list(page_context.get("elements")),
        }

    def _serialize_registry_targets(
        self,
        *,
        registry: NavigationTargetRegistry,
    ) -> list[NavigationTargetResult]:
        records: list[NavigationTargetResult] = []
        for target in registry.targets:
            records.append(NavigationTargetResult.model_validate(target.to_record()))
        for target in registry.rejected_targets:
            records.append(NavigationTargetResult.model_validate(target.to_record()))
        return records

    def _action_payload_rejection_reason(self, payload: dict[str, object]) -> str:
        for key in ("probe_apply_reason", "reason"):
            value = self._clean_text(payload.get(key))
            if value is not None:
                return value.lower().replace("-", "_")
        return "state_transition_not_applied"

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

    def _action_payload_applied(self, payload: dict[str, object]) -> bool:
        applied = payload.get("probe_applied", payload.get("applied"))
        if isinstance(applied, bool):
            return applied
        return True

    def _to_state_payload(
        self,
        *,
        default_route: str,
        action: dict[str, object],
        payload: dict[str, object],
        page_context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        merged: dict[str, object] = {}
        merged.update(action)
        merged.update(payload)
        if page_context is not None:
            merged = dict(page_context) | merged

        route_path = self._normalize_route_path(
            merged.get("route_path") or merged.get("page_route_path") or default_route
        )
        merged["route_path"] = route_path or default_route

        state_context = merge_state_context(
            page_context.get("state_context") if isinstance(page_context, dict) else None,
            action.get("state_context"),
            payload.get("state_context"),
            merged.get("state_context"),
        )
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

    def _append_warnings(self, warnings: list[str], reasons: object) -> None:
        if not isinstance(reasons, list):
            return
        for reason in reasons:
            normalized = self._clean_text(reason)
            if normalized is not None:
                self._append_warning(warnings, normalized)

    def _escape_quote(self, value: str) -> str:
        return value.replace("'", "\\'")

    def _clean_text(self, value: object) -> str | None:
        if not isinstance(value, str):
            return None
        cleaned = value.strip()
        return cleaned or None


def merge_state_context(*contexts: object) -> dict[str, object]:
    merged: dict[str, object] = {}
    for value in contexts:
        if not isinstance(value, dict):
            continue
        for key, raw in value.items():
            if not isinstance(key, str):
                continue
            clean_key = key.strip()
            if not clean_key:
                continue
            if isinstance(raw, str):
                cleaned = raw.strip()
                if cleaned:
                    merged[clean_key] = cleaned
            elif isinstance(raw, (int, float, bool)):
                merged[clean_key] = raw
    return merged


def build_navigation_action_payload(
    *,
    target: NavigationTarget | dict[str, object],
    route_path: str | None = None,
    base_state_context: object = None,
) -> dict[str, object]:
    record = target.to_record() if isinstance(target, NavigationTarget) else dict(target)
    target_kind = record.get("target_kind")
    entry_type = _normalize_action_name(
        record.get("entry_type") or record.get("interaction_type") or target_kind
    )
    payload = dict(record)
    normalized_route = _normalize_action_route(route_path or record.get("route_path") or record.get("route_hint"))
    if normalized_route is not None:
        payload["route_path"] = normalized_route
        payload["page_route_path"] = normalized_route
        payload["route_hint"] = normalized_route
    if entry_type is not None:
        payload["entry_type"] = entry_type
        payload["interaction_type"] = entry_type
    payload["state_context"] = merge_state_context(base_state_context, payload.get("state_context"))
    return payload


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


def _normalize_action_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned.lower().replace("-", "_")


def _normalize_action_route(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    route_path = value.strip()
    if not route_path or not route_path.startswith("/"):
        return None
    return route_path.rstrip("/") or "/"
