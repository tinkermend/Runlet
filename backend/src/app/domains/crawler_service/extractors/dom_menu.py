from __future__ import annotations

from typing import Any, Protocol

from app.domains.crawler_service.schemas import CrawlExtractionResult, ElementCandidate, MenuCandidate


def build_menu_expand_targets(skeleton: list[dict[str, Any]]) -> list[dict[str, object]]:
    targets: list[dict[str, object]] = []
    seen: set[tuple[object, ...]] = set()
    for item in skeleton:
        if not isinstance(item, dict):
            continue
        label = _clean_text_value(item.get("label") or item.get("text") or item.get("name"))
        if label is None:
            continue
        entry_type = _normalize_entry_type_value(item.get("entry_type") or item.get("interaction_type"))
        aria_expanded = _clean_text_value(item.get("aria_expanded"))
        if entry_type not in {"menu_expand", "tree_expand", "expand_panel"} and aria_expanded != "false":
            continue
        target_kind = "tree_expand" if entry_type == "tree_expand" else "menu_expand"
        parent_label = _clean_text_value(item.get("parent_label"))
        depth = _to_int_value(item.get("depth"))
        sibling_index = _to_optional_int_value(item.get("sibling_index"))
        order = _to_int_value(item.get("order") or item.get("sort_order"))
        route_path = _normalize_path_value(item.get("route_path") or item.get("path"))
        page_route_path = _normalize_path_value(item.get("page_route_path") or item.get("route_path"))
        dedupe_key = (
            target_kind,
            *_menu_identity_fields(
                label=label,
                parent_label=parent_label,
                depth=depth,
                role=_clean_text_value(item.get("role")),
                aria_label=_clean_text_value(item.get("aria_label")),
                sibling_index=sibling_index,
            ),
            route_path,
            page_route_path,
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        targets.append(
            {
                "target_kind": target_kind,
                "label": label,
                "parent_label": parent_label,
                "depth": depth,
                "sibling_index": sibling_index,
                "order": order,
                "role": _clean_text_value(item.get("role")),
                "aria_label": _clean_text_value(item.get("aria_label")),
                "route_path": route_path,
                "page_route_path": page_route_path,
                "locator_candidates": _build_menu_locator_candidates(item=item, label=label),
            }
        )
    return targets


def merge_menu_skeleton_and_materialized_nodes(
    *,
    skeleton: list[dict[str, Any]],
    materialized: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    index_by_key: dict[tuple[object, ...], int] = {}

    for raw_item in [*skeleton, *materialized]:
        normalized = _normalize_menu_node(raw_item)
        if normalized is None:
            continue
        key = _menu_identity_fields(
            label=normalized["label"],
            parent_label=normalized.get("parent_label"),
            depth=normalized["depth"],
            role=normalized.get("role"),
            aria_label=normalized.get("aria_label"),
            sibling_index=_to_optional_int_value(normalized.get("sibling_index")),
        )
        existing_index = index_by_key.get(key)
        if existing_index is None:
            if "order" not in normalized:
                normalized["order"] = len(merged)
            merged.append(normalized)
            index_by_key[key] = len(merged) - 1
            continue
        existing = merged[existing_index]
        for field_name in ("role", "aria_label", "entry_type", "aria_expanded"):
            if existing.get(field_name) is None and normalized.get(field_name) is not None:
                existing[field_name] = normalized[field_name]
        for field_name in ("route_path", "page_route_path"):
            existing[field_name] = _prefer_menu_route_fact(
                existing_value=existing.get(field_name),
                incoming_value=normalized.get(field_name),
            )
        if existing.get("parent_label") is None and normalized.get("parent_label") is not None:
            existing["parent_label"] = normalized["parent_label"]

    return merged


class DomMenuExtractor(Protocol):
    async def extract(
        self,
        *,
        browser_session,
        system,
        crawl_scope: str,
    ) -> CrawlExtractionResult: ...


class NullDomMenuExtractor:
    async def extract(
        self,
        *,
        browser_session,
        system,
        crawl_scope: str,
    ) -> CrawlExtractionResult:
        del browser_session, system, crawl_scope
        return CrawlExtractionResult()


class DomMenuTraversalExtractor:
    _TABLE_CLASS_MARKERS = (
        "el-table",
        "vxe-table",
        "ant-table",
        "ivu-table",
        "n-data-table",
        "ag-root",
        "ag-theme",
    )

    async def extract(
        self,
        *,
        browser_session,
        system,
        crawl_scope: str,
    ) -> CrawlExtractionResult:
        del system
        warnings: list[str] = []
        failure_reason: str | None = None
        try:
            menu_items = await self._collect_menu_items(
                browser_session=browser_session,
                crawl_scope=crawl_scope,
            )
            element_items = await self._collect_element_items(
                browser_session=browser_session,
                crawl_scope=crawl_scope,
            )
        except Exception as exc:  # pragma: no cover - exercised via service tests
            menu_items = []
            element_items = []
            failure_reason = f"dom traversal extraction failed: {exc}"
            warnings.append(f"dom traversal degraded: {exc}")

        menus = [self._to_menu_candidate(item) for item in menu_items]
        menus = [candidate for candidate in menus if candidate is not None]

        elements = [self._to_element_candidate(item) for item in element_items]
        elements = [candidate for candidate in elements if candidate is not None]

        quality_score = min(1.0, 0.4 + (0.08 * len(menus)) + (0.04 * len(elements)))
        return CrawlExtractionResult(
            quality_score=quality_score,
            menus=menus,
            elements=elements,
            failure_reason=failure_reason,
            warning_messages=warnings,
            degraded=len(menus) == 0 and len(elements) == 0,
        )

    async def collect_navigation_signals(
        self,
        *,
        browser_session,
        crawl_scope: str,
    ) -> list[dict[str, Any]]:
        menu_items = await self._collect_menu_items(browser_session=browser_session, crawl_scope=crawl_scope)
        signals: list[dict[str, Any]] = []
        for item in menu_items:
            route_path = self._normalize_path(item.get("route_path") or item.get("path"))
            page_route_path = self._normalize_path(item.get("page_route_path") or route_path)
            if route_path is None and page_route_path is None:
                continue
            signal: dict[str, Any] = {
                "route_path": route_path,
                "page_route_path": page_route_path,
                "label": self._clean_text(item.get("label") or item.get("text") or item.get("name")),
                "discovery_sources": ["dom_menu_tree"],
            }
            entry_type = self._normalize_entry_type(item.get("entry_type") or item.get("interaction_type"))
            if entry_type is not None:
                signal["entry_type"] = entry_type
            context_constraints = item.get("context_constraints")
            if isinstance(context_constraints, dict):
                signal["context_constraints"] = context_constraints
            signals.append(signal)
        return signals

    async def _collect_menu_items(self, *, browser_session, crawl_scope: str) -> list[dict[str, Any]]:
        collector = getattr(browser_session, "collect_dom_menu_nodes", None)
        if callable(collector):
            return self._ensure_dict_list(await collector(crawl_scope=crawl_scope))
        skeleton_collector = getattr(browser_session, "collect_dom_menu_skeleton", None)
        if callable(skeleton_collector):
            skeleton = self._ensure_dict_list(await skeleton_collector(crawl_scope=crawl_scope))
            materializer = getattr(browser_session, "materialize_navigation_targets", None)
            if callable(materializer):
                materialized = self._ensure_dict_list(
                    await materializer(
                        targets=build_menu_expand_targets(skeleton),
                        crawl_scope=crawl_scope,
                    )
                )
                return merge_menu_skeleton_and_materialized_nodes(
                    skeleton=skeleton,
                    materialized=materialized,
                )
            return skeleton
        return self._ensure_dict_list(getattr(browser_session, "dom_menu_nodes", []))

    async def _collect_element_items(self, *, browser_session, crawl_scope: str) -> list[dict[str, Any]]:
        collector = getattr(browser_session, "collect_dom_elements", None)
        if callable(collector):
            return self._ensure_dict_list(await collector(crawl_scope=crawl_scope))
        return self._ensure_dict_list(getattr(browser_session, "dom_elements", []))

    def _to_menu_candidate(self, item: dict[str, Any]) -> MenuCandidate | None:
        label = self._clean_text(item.get("label") or item.get("text") or item.get("name"))
        if label is None:
            return None
        route_path = self._normalize_path(item.get("route_path") or item.get("path"))
        role = self._clean_text(item.get("role"))
        aria_label = self._clean_text(item.get("aria_label"))
        locator = self._build_locator(
            role=role,
            text=label,
            aria_label=aria_label,
            fallback_tag="li",
        )
        entry_candidates: list[dict[str, object]] = []
        entry_type = self._normalize_entry_type(item.get("entry_type") or item.get("interaction_type"))
        if entry_type is not None:
            entry_candidates.append(
                {
                    "entry_type": entry_type,
                    "label": label,
                }
            )
        return MenuCandidate(
            label=label,
            route_path=route_path,
            depth=self._to_int(item.get("depth")),
            sort_order=self._to_int(item.get("order") or item.get("sort_order")),
            playwright_locator=locator,
            parent_label=self._clean_text(item.get("parent_label")),
            page_route_path=self._normalize_path(item.get("page_route_path") or route_path),
            discovery_sources=["dom_menu_tree"],
            entry_candidates=entry_candidates,
        )

    def _to_element_candidate(self, item: dict[str, Any]) -> ElementCandidate | None:
        page_route_path = self._normalize_path(item.get("page_route_path") or item.get("route_path"))
        if page_route_path is None:
            return None
        if not self._is_visible(item):
            return None
        element_type = self._normalize_element_type(item)
        if element_type is None:
            return None
        role = self._clean_text(item.get("role") or item.get("element_role"))
        text = self._clean_text(item.get("text") or item.get("element_text") or item.get("name"))
        aria_label = self._clean_text(item.get("aria_label"))
        locator = self._build_locator(
            role=role,
            text=text,
            aria_label=aria_label,
            fallback_tag=element_type,
        )
        return ElementCandidate(
            page_route_path=page_route_path,
            element_type=element_type,
            element_role=role,
            element_text=text,
            attributes=self._to_dict_or_none(item.get("attributes")),
            playwright_locator=locator,
            stability_score=self._to_float(item.get("stability_score")) or 0.7,
            usage_description=self._clean_text(item.get("usage_description")),
        )

    def _build_locator(
        self,
        *,
        role: str | None,
        text: str | None,
        aria_label: str | None,
        fallback_tag: str,
    ) -> str:
        if role and text:
            return f"role={role}[name='{self._escape_quote(text)}']"
        if role and aria_label:
            return f"role={role}[name='{self._escape_quote(aria_label)}']"
        if text:
            return f"text='{self._escape_quote(text)}'"
        if aria_label:
            return f"css=[aria-label='{self._escape_quote(aria_label)}']"
        return f"css={fallback_tag}"

    def _escape_quote(self, value: str) -> str:
        return value.replace("'", "\\'")

    def _is_visible(self, item: dict[str, Any]) -> bool:
        visible = item.get("visible")
        if isinstance(visible, bool):
            return visible
        return True

    def _normalize_element_type(self, item: dict[str, Any]) -> str | None:
        raw_type = self._clean_text(item.get("element_type") or item.get("tag_name"))
        role = self._clean_text(item.get("role") or item.get("element_role"))
        class_name = self._clean_text(item.get("class_name"))

        if raw_type == "table":
            return "table"
        if role in {"grid", "table"}:
            return "table"
        if class_name and any(marker in class_name for marker in self._TABLE_CLASS_MARKERS):
            return "table"
        return raw_type

    def _ensure_dict_list(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        result: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                result.append(item)
        return result

    def _to_int(self, value: Any) -> int:
        if isinstance(value, bool):
            return 0
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.isdigit():
                return int(stripped)
        return 0

    def _to_float(self, value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (float, int)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                return None
        return None

    def _to_dict_or_none(self, value: Any) -> dict[str, object] | None:
        if isinstance(value, dict):
            return value
        return None

    def _normalize_path(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        path = value.strip()
        if not path or not path.startswith("/"):
            return None
        return path

    def _clean_text(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        cleaned = value.strip()
        return cleaned or None

    def _normalize_entry_type(self, value: Any) -> str | None:
        return _normalize_entry_type_value(value)


def _normalize_menu_node(item: dict[str, Any]) -> dict[str, Any] | None:
    label = _clean_text_value(item.get("label") or item.get("text") or item.get("name"))
    if label is None:
        return None
    normalized: dict[str, Any] = {
        "label": label,
        "route_path": _normalize_path_value(item.get("route_path") or item.get("path")),
        "page_route_path": _normalize_path_value(item.get("page_route_path") or item.get("route_path")),
        "depth": _to_int_value(item.get("depth")),
        "order": _to_int_value(item.get("order") or item.get("sort_order")),
        "role": _clean_text_value(item.get("role")),
        "aria_label": _clean_text_value(item.get("aria_label")),
        "sibling_index": _to_optional_int_value(item.get("sibling_index")),
        "parent_label": _clean_text_value(
            item.get("parent_label") or item.get("materialized_parent_label") or item.get("parent")
        ),
        "entry_type": _normalize_entry_type_value(item.get("entry_type") or item.get("interaction_type")),
        "aria_expanded": _clean_text_value(item.get("aria_expanded")),
    }
    return normalized


def _build_menu_locator_candidates(*, item: dict[str, Any], label: str) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = [{"strategy_type": "text", "selector": label}]
    role = _clean_text_value(item.get("role"))
    if role is not None:
        candidates.append({"strategy_type": "role", "selector": role, "label": label})
    aria_label = _clean_text_value(item.get("aria_label"))
    if aria_label is not None:
        candidates.append({"strategy_type": "aria_label", "selector": aria_label})
    route_path = _normalize_path_value(item.get("route_path") or item.get("page_route_path"))
    if route_path is not None:
        candidates.append({"strategy_type": "route_path", "selector": route_path})
    sibling_index = _to_optional_int_value(item.get("sibling_index"))
    if sibling_index is not None:
        candidates.append({"strategy_type": "sibling_index", "selector": str(sibling_index)})
    order = _to_int_value(item.get("order") or item.get("sort_order"))
    candidates.append({"strategy_type": "order", "selector": str(order)})
    return candidates


def _menu_identity_fields(
    *,
    label: str,
    parent_label: str | None,
    depth: int,
    role: str | None,
    aria_label: str | None,
    sibling_index: int | None,
) -> tuple[object, ...]:
    return (
        label,
        parent_label,
        depth,
        role,
        aria_label,
        sibling_index,
    )


def _prefer_menu_route_fact(*, existing_value: Any, incoming_value: Any) -> str | None:
    existing = _normalize_path_value(existing_value)
    incoming = _normalize_path_value(incoming_value)
    if incoming is None:
        return existing
    if existing is None:
        return incoming
    if existing != incoming:
        return incoming
    return existing


def _normalize_entry_type_value(value: Any) -> str | None:
    clean_value = _clean_text_value(value)
    if clean_value is None:
        return None
    normalized = clean_value.strip().lower().replace("-", "_")
    if normalized in {"tab", "switch_tab"}:
        return "tab_switch"
    if normalized in {"modal", "show_modal"}:
        return "open_modal"
    if normalized in {"drawer", "show_drawer"}:
        return "open_drawer"
    if normalized in {"expand_filter", "open_filter", "toggle_filter"}:
        return "filter_expand"
    return normalized


def _normalize_path_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    path = value.strip()
    if not path or not path.startswith("/"):
        return None
    return path


def _clean_text_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _to_int_value(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
    return 0


def _to_optional_int_value(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
    return None
