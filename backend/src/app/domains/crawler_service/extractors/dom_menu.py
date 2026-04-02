from __future__ import annotations

from typing import Any, Protocol

from app.domains.crawler_service.schemas import CrawlExtractionResult, ElementCandidate, MenuCandidate


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

    async def _collect_menu_items(self, *, browser_session, crawl_scope: str) -> list[dict[str, Any]]:
        collector = getattr(browser_session, "collect_dom_menu_nodes", None)
        if callable(collector):
            return self._ensure_dict_list(await collector(crawl_scope=crawl_scope))
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
        return MenuCandidate(
            label=label,
            route_path=route_path,
            depth=self._to_int(item.get("depth")),
            sort_order=self._to_int(item.get("order") or item.get("sort_order")),
            playwright_locator=locator,
            parent_label=self._clean_text(item.get("parent_label")),
            page_route_path=self._normalize_path(item.get("page_route_path") or route_path),
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
