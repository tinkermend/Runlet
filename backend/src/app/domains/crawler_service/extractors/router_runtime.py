from __future__ import annotations

from typing import Any, Protocol

from app.domains.crawler_service.schemas import CrawlExtractionResult, PageCandidate


class RouterRuntimeExtractor(Protocol):
    async def extract(
        self,
        *,
        browser_session,
        system,
        crawl_scope: str,
    ) -> CrawlExtractionResult: ...


class NullRouterRuntimeExtractor:
    async def extract(
        self,
        *,
        browser_session,
        system,
        crawl_scope: str,
    ) -> CrawlExtractionResult:
        del browser_session, system, crawl_scope
        return CrawlExtractionResult()


class RuntimeRouteHintExtractor:
    async def collect_route_signals(
        self,
        *,
        browser_session,
        crawl_scope: str,
    ) -> list[dict[str, Any]]:
        route_hints = await self._collect_route_hints(
            browser_session=browser_session,
            crawl_scope=crawl_scope,
        )
        route_snapshot = await self._collect_route_snapshot(
            browser_session=browser_session,
            crawl_scope=crawl_scope,
        )
        merged_by_route: dict[str, dict[str, Any]] = {}
        for hint in route_hints:
            route_path = self._normalize_path(hint.get("path") or hint.get("route_path"))
            if route_path is None:
                continue
            signal: dict[str, Any] = {
                "route_path": route_path,
                "discovery_sources": ["runtime_route_hints"],
            }
            page_title = self._to_clean_text(hint.get("title") or hint.get("label") or hint.get("name"))
            if page_title is not None:
                signal["page_title"] = page_title
            context_constraints = hint.get("context_constraints")
            if isinstance(context_constraints, dict):
                signal["context_constraints"] = context_constraints
            merged_by_route[route_path] = signal

        resolved_route = self._normalize_path(route_snapshot.get("resolved_route"))
        if resolved_route == "/" and any(route != "/" for route in merged_by_route):
            resolved_route = None
        if resolved_route is not None:
            route_source = self._to_clean_text(route_snapshot.get("route_source")) or "runtime_snapshot"
            snapshot_signal: dict[str, Any] = {
                "route_path": resolved_route,
                "discovery_sources": ["runtime_route_snapshot"],
                "context_constraints": {"route_source": route_source},
                "navigation_diagnostics": {
                    "resolved_route": resolved_route,
                    "route_source": route_source,
                },
            }
            existing = merged_by_route.get(resolved_route)
            if existing is None:
                merged_by_route[resolved_route] = snapshot_signal
            else:
                existing_sources = existing.get("discovery_sources")
                if not isinstance(existing_sources, list):
                    existing_sources = []
                for source in snapshot_signal["discovery_sources"]:
                    if source not in existing_sources:
                        existing_sources.append(source)
                existing["discovery_sources"] = existing_sources

                existing_context = existing.get("context_constraints")
                if not isinstance(existing_context, dict):
                    existing_context = {}
                snapshot_context = snapshot_signal["context_constraints"]
                existing["context_constraints"] = {**snapshot_context, **existing_context}
                if not isinstance(existing.get("navigation_diagnostics"), dict):
                    existing["navigation_diagnostics"] = dict(snapshot_signal["navigation_diagnostics"])
        return list(merged_by_route.values())

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
        pages: list[PageCandidate] = []
        try:
            route_signals = await self.collect_route_signals(
                browser_session=browser_session,
                crawl_scope=crawl_scope,
            )
        except Exception as exc:  # pragma: no cover - exercised via service tests
            route_signals = []
            failure_reason = f"runtime route hint extraction failed: {exc}"
            warnings.append(f"route hints degraded: {exc}")

        seen: set[str] = set()
        for signal in route_signals:
            route_path = self._normalize_path(signal.get("route_path"))
            if route_path is None or route_path in seen:
                continue
            seen.add(route_path)
            page_title = self._to_clean_text(signal.get("page_title"))
            discovery_sources = signal.get("discovery_sources")
            pages.append(
                PageCandidate(
                    route_path=route_path,
                    page_title=page_title,
                    discovery_sources=discovery_sources if isinstance(discovery_sources, list) else [],
                    navigation_diagnostics=(
                        dict(signal.get("navigation_diagnostics"))
                        if isinstance(signal.get("navigation_diagnostics"), dict)
                        else None
                    ),
                )
            )

        quality_score = min(1.0, 0.6 + (0.1 * len(pages))) if pages else 0.0
        return CrawlExtractionResult(
            framework_detected=self._to_clean_text(getattr(browser_session, "framework_hint", None)),
            quality_score=quality_score,
            pages=pages,
            failure_reason=failure_reason,
            warning_messages=warnings,
            degraded=len(pages) == 0,
        )

    async def _collect_route_hints(self, *, browser_session, crawl_scope: str) -> list[dict[str, Any]]:
        collector = getattr(browser_session, "collect_route_hints", None)
        if callable(collector):
            collected = await collector(crawl_scope=crawl_scope)
            return self._ensure_dict_list(collected)
        return self._ensure_dict_list(getattr(browser_session, "route_hints", []))

    async def _collect_route_snapshot(self, *, browser_session, crawl_scope: str) -> dict[str, Any]:
        collector = getattr(browser_session, "collect_route_snapshot", None)
        if not callable(collector):
            return {}
        try:
            collected = await collector(crawl_scope=crawl_scope)
        except Exception:
            return {}
        if isinstance(collected, dict):
            return collected
        return {}

    def _ensure_dict_list(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        result: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                result.append(item)
        return result

    def _normalize_path(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        path = value.strip()
        if not path or not path.startswith("/"):
            return None
        path = path.split("#", 1)[0].split("?", 1)[0].strip()
        if not path or not path.startswith("/"):
            return None
        return path.rstrip("/") or "/"

    def _to_clean_text(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        text = value.strip()
        return text or None
