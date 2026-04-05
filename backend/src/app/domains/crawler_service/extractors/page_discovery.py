from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse

from app.domains.crawler_service.extractors.dom_menu import DomMenuTraversalExtractor
from app.domains.crawler_service.extractors.router_runtime import RuntimeRouteHintExtractor
from app.domains.crawler_service.navigation_targets import NavigationTarget, NavigationTargetRegistry

from app.domains.crawler_service.schemas import (
    CrawlExtractionResult,
    NavigationTargetResult,
    PageCandidate,
)


class PageDiscoveryProtocol(Protocol):
    async def extract(
        self,
        *,
        browser_session,
        system,
        crawl_scope: str,
    ) -> CrawlExtractionResult: ...


class PageDiscoveryExtractor:
    _ENTRY_TYPES = {"tab_switch", "open_modal", "open_drawer", "filter_expand"}
    _SOURCE_PRIORITY = {
        "runtime_route_hints": 0,
        "dom_menu_tree": 1,
        "network_route_config": 2,
        "network_resource": 3,
        "network_request": 4,
        "reachability_probe": 5,
    }

    def __init__(
        self,
        *,
        runtime_extractor: RuntimeRouteHintExtractor | None = None,
        dom_menu_extractor: DomMenuTraversalExtractor | None = None,
    ) -> None:
        self.runtime_extractor = runtime_extractor or RuntimeRouteHintExtractor()
        self.dom_menu_extractor = dom_menu_extractor or DomMenuTraversalExtractor()

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

        route_signals = await self._collect_with_degrade(
            collector=lambda: self._collect_route_signals(
                browser_session=browser_session,
                crawl_scope=crawl_scope,
            ),
            label="route signals",
            warnings=warnings,
        )
        nav_signals = await self._collect_with_degrade(
            collector=lambda: self._collect_navigation_signals(
                browser_session=browser_session,
                crawl_scope=crawl_scope,
            ),
            label="navigation signals",
            warnings=warnings,
        )
        network_signals = await self._collect_network_signals(
            browser_session=browser_session,
            crawl_scope=crawl_scope,
            warnings=warnings,
        )
        metadata_signals = await self._collect_with_degrade(
            collector=lambda: self._collect_page_metadata_signals(
                browser_session=browser_session,
                crawl_scope=crawl_scope,
            ),
            label="page metadata validation",
            warnings=warnings,
        )

        page_store: dict[str, _PageStore] = {}
        quality_hints: list[float] = []
        framework_hints: list[str] = []
        merged_signals = [*route_signals, *nav_signals, *network_signals]
        target_registry = NavigationTargetRegistry()
        grouped_targets = self._group_navigation_targets(merged_signals)
        for group in grouped_targets.values():
            target_registry.add(group.target)

        for target in target_registry.targets:
            group = grouped_targets.get(target.dedupe_key())
            if group is None:
                continue
            route_path = target.route_hint
            if route_path is None:
                continue
            page = page_store.setdefault(route_path, _PageStore())
            for seed in group.seeds:
                self._merge_signal_to_page(
                    page=page,
                    signal=seed.signal,
                    entry_candidates=[seed.entry_candidate] if seed.entry_candidate is not None else [],
                    include_label_as_title=seed.include_label_as_title,
                )
                self._collect_extraction_hints(
                    signal=seed.signal,
                    quality_hints=quality_hints,
                    framework_hints=framework_hints,
                )

        for metadata in metadata_signals:
            route_path = self._extract_route_path(metadata)
            if route_path is None or route_path not in page_store:
                continue
            page = page_store[route_path]
            page.title = page.title or self._clean_text(metadata.get("page_title") or metadata.get("title"))
            reachable = metadata.get("reachable")
            if isinstance(reachable, bool):
                page.context_constraints.setdefault("reachable", reachable)
            status_code = metadata.get("status_code")
            if isinstance(status_code, int):
                page.context_constraints.setdefault("status_code", status_code)

        pages: list[PageCandidate] = []
        all_sources: set[str] = set()
        for route_path in sorted(page_store):
            page = page_store[route_path]
            discovery_sources = sorted(
                page.sources,
                key=lambda source: (self._SOURCE_PRIORITY.get(source, 100), source),
            )
            all_sources.update(discovery_sources)
            pages.append(
                PageCandidate(
                    route_path=route_path,
                    page_title=page.title,
                    discovery_sources=discovery_sources,
                    entry_candidates=page.entry_candidates,
                    context_constraints=page.context_constraints or None,
                )
            )

        quality_score = 0.0
        if pages:
            quality_score = min(1.0, 0.4 + (0.08 * len(pages)) + (0.03 * len(all_sources)))
            if quality_hints:
                quality_score = max(quality_score, max(quality_hints))

        framework_detected = self._clean_text(getattr(browser_session, "framework_hint", None))
        if framework_detected is None and framework_hints:
            framework_detected = framework_hints[0]

        degraded = len(pages) == 0
        if degraded:
            failure_reason = warnings[0] if warnings else "page discovery produced no usable page candidates"
        else:
            failure_reason = None

        return CrawlExtractionResult(
            framework_detected=framework_detected,
            quality_score=quality_score,
            pages=pages,
            navigation_targets=[
                NavigationTargetResult.model_validate(target.to_record()) for target in target_registry.targets
            ],
            failure_reason=failure_reason,
            warning_messages=warnings,
            degraded=degraded,
        )

    def _group_navigation_targets(
        self,
        signals: list[dict[str, Any]],
    ) -> dict[str, "_NavigationTargetGroup"]:
        grouped_targets: dict[str, _NavigationTargetGroup] = {}
        for signal in signals:
            for seed in self._build_target_seeds(signal):
                dedupe_key = seed.target.dedupe_key()
                group = grouped_targets.get(dedupe_key)
                if group is None:
                    grouped_targets[dedupe_key] = _NavigationTargetGroup(target=seed.target, seeds=[seed])
                    continue
                group.target.merge_from(seed.target)
                group.seeds.append(seed)
        return grouped_targets

    def _build_target_seeds(self, signal: dict[str, Any]) -> list["_NavigationTargetSeed"]:
        entry_candidates = self._to_entry_candidates(signal)
        interaction_only = self._is_interaction_only_signal(signal=signal, entry_candidates=entry_candidates)
        route_path = self._extract_route_path(signal)
        seeds: list[_NavigationTargetSeed] = []
        if not interaction_only and route_path is not None:
            seeds.append(
                _NavigationTargetSeed(
                    target=NavigationTarget(
                        target_kind="page_route",
                        route_hint=route_path,
                        discovery_source=self._primary_source(signal),
                        metadata={"discovery_sources": sorted(self._extract_sources(signal))},
                    ),
                    signal=signal,
                    entry_candidate=None,
                    include_label_as_title=True,
                )
            )

        for entry_candidate in entry_candidates:
            target = self._build_interaction_target(signal=signal, entry_candidate=entry_candidate, default_route=route_path)
            if target is None:
                continue
            seeds.append(
                _NavigationTargetSeed(
                    target=target,
                    signal=signal,
                    entry_candidate=entry_candidate,
                    include_label_as_title=False,
                )
            )
        return seeds

    def _build_interaction_target(
        self,
        *,
        signal: dict[str, Any],
        entry_candidate: dict[str, object],
        default_route: str | None,
    ) -> NavigationTarget | None:
        entry_type = self._normalize_entry_type(entry_candidate.get("entry_type"))
        if entry_type is None:
            return None
        page_route = self._normalize_path(signal.get("page_route_path")) or default_route
        if page_route is None:
            return None
        return NavigationTarget(
            target_kind=entry_type,
            route_hint=page_route,
            locator_candidates=self._build_locator_candidates(signal=signal, entry_candidate=entry_candidate),
            state_context=self._build_state_context(signal=signal, entry_candidate=entry_candidate),
            parent_target_key=f"page:{page_route}",
            discovery_source=self._primary_source(signal),
            metadata={"discovery_sources": sorted(self._extract_sources(signal))},
        )

    def _build_state_context(
        self,
        *,
        signal: dict[str, Any],
        entry_candidate: dict[str, object],
    ) -> dict[str, object]:
        entry_type = self._normalize_entry_type(entry_candidate.get("entry_type"))
        label = self._clean_text(
            entry_candidate.get("label")
            or signal.get("label")
            or signal.get("text")
            or signal.get("name")
            or signal.get("title")
        )
        state_context: dict[str, object] = {}
        if entry_type == "tab_switch" and label is not None:
            state_context["active_tab"] = label
        elif entry_type == "open_modal" and label is not None:
            state_context["modal_title"] = label
        elif entry_type == "open_drawer" and label is not None:
            state_context["drawer_title"] = label
        elif entry_type == "filter_expand" and label is not None:
            state_context["panel_title"] = label

        target_route = self._extract_route_path(signal)
        page_route = self._normalize_path(signal.get("page_route_path"))
        if (
            target_route is not None
            and page_route is not None
            and target_route != page_route
            and "target_route" not in state_context
        ):
            state_context["target_route"] = target_route
        return state_context

    def _build_locator_candidates(
        self,
        *,
        signal: dict[str, Any],
        entry_candidate: dict[str, object],
    ) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        for source in (
            entry_candidate.get("locator_candidates"),
            signal.get("locator_candidates"),
        ):
            if isinstance(source, list):
                for candidate in source:
                    if isinstance(candidate, dict):
                        candidates.append(candidate)
        playwright_locator = self._clean_text(
            entry_candidate.get("playwright_locator") or signal.get("playwright_locator")
        )
        if playwright_locator is not None:
            candidates.append({"strategy_type": "playwright", "selector": playwright_locator})
        return candidates

    def _primary_source(self, signal: dict[str, Any]) -> str | None:
        sources = sorted(self._extract_sources(signal))
        if sources:
            return sources[0]
        return None

    async def _collect_route_signals(
        self,
        *,
        browser_session,
        crawl_scope: str,
    ) -> list[dict[str, Any]]:
        collector = getattr(self.runtime_extractor, "collect_route_signals", None)
        if callable(collector):
            return self._ensure_dict_list(await collector(browser_session=browser_session, crawl_scope=crawl_scope))

        extract = getattr(self.runtime_extractor, "extract", None)
        if callable(extract):
            extraction_result = await extract(
                browser_session=browser_session,
                system=None,
                crawl_scope=crawl_scope,
            )
            signals: list[dict[str, Any]] = []
            for page in extraction_result.pages:
                signals.append(
                    {
                        "route_path": page.route_path,
                        "page_title": page.page_title,
                        "discovery_sources": page.discovery_sources or ["runtime_route_hints"],
                        "entry_candidates": page.entry_candidates,
                        "context_constraints": page.context_constraints,
                        "quality_score_hint": extraction_result.quality_score,
                        "framework_hint": extraction_result.framework_detected,
                    }
                )
            return signals

        return self._ensure_dict_list(
            await self._collect_session_facts(
                browser_session=browser_session,
                crawl_scope=crawl_scope,
                method_name="collect_route_hints",
                attr_name="route_hints",
                source="runtime_route_hints",
            )
        )

    async def _collect_navigation_signals(
        self,
        *,
        browser_session,
        crawl_scope: str,
    ) -> list[dict[str, Any]]:
        collector = getattr(self.dom_menu_extractor, "collect_navigation_signals", None)
        if callable(collector):
            return self._ensure_dict_list(await collector(browser_session=browser_session, crawl_scope=crawl_scope))
        return self._ensure_dict_list(
            await self._collect_session_facts(
                browser_session=browser_session,
                crawl_scope=crawl_scope,
                method_name="collect_dom_menu_nodes",
                attr_name="dom_menu_nodes",
                source="dom_menu_tree",
            )
        )

    async def _collect_network_signals(
        self,
        *,
        browser_session,
        crawl_scope: str,
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        route_configs = await self._collect_with_degrade(
            collector=lambda: self._collect_session_facts(
                browser_session=browser_session,
                crawl_scope=crawl_scope,
                method_name="collect_network_route_configs",
                attr_name="network_route_configs",
                source="network_route_config",
            ),
            label="network route config signals",
            warnings=warnings,
        )
        resource_hints = await self._collect_with_degrade(
            collector=lambda: self._collect_session_facts(
                browser_session=browser_session,
                crawl_scope=crawl_scope,
                method_name="collect_network_resource_hints",
                attr_name="network_resource_hints",
                source="network_resource",
            ),
            label="network resource signals",
            warnings=warnings,
        )
        request_hints = await self._collect_with_degrade(
            collector=lambda: self._collect_session_facts(
                browser_session=browser_session,
                crawl_scope=crawl_scope,
                method_name="collect_network_requests",
                attr_name="network_requests",
                source="network_request",
            ),
            label="network request signals",
            warnings=warnings,
        )
        return self._ensure_dict_list([*route_configs, *resource_hints, *request_hints])

    async def _collect_page_metadata_signals(
        self,
        *,
        browser_session,
        crawl_scope: str,
    ) -> list[dict[str, Any]]:
        return self._ensure_dict_list(
            await self._collect_session_facts(
                browser_session=browser_session,
                crawl_scope=crawl_scope,
                method_name="collect_page_metadata",
                attr_name="page_metadata",
                source="reachability_probe",
            )
        )

    async def _collect_session_facts(
        self,
        *,
        browser_session,
        crawl_scope: str,
        method_name: str,
        attr_name: str,
        source: str,
    ) -> list[dict[str, Any]]:
        collector = getattr(browser_session, method_name, None)
        if callable(collector):
            raw_value = await collector(crawl_scope=crawl_scope)
        else:
            raw_value = getattr(browser_session, attr_name, [])
        records = self._ensure_dict_list(raw_value)
        for record in records:
            sources = self._extract_sources(record)
            if source not in sources:
                sources.add(source)
            record["discovery_sources"] = sorted(sources)
        return records

    async def _collect_with_degrade(
        self,
        *,
        collector,
        label: str,
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        try:
            return await collector()
        except Exception as exc:  # pragma: no cover - exercised via service tests
            warnings.append(f"{label} degraded: {exc}")
            return []

    def _extract_route_path(self, signal: dict[str, Any]) -> str | None:
        route_path = signal.get("route_path") or signal.get("page_route_path") or signal.get("path")
        if route_path is None and isinstance(signal.get("url"), str):
            route_path = signal["url"]
        return self._normalize_path(route_path)

    def _resolve_interaction_target_route(
        self,
        *,
        signal: dict[str, Any],
        page_store: dict[str, "_PageStore"],
    ) -> str | None:
        page_route_path = self._normalize_path(signal.get("page_route_path"))
        if page_route_path is not None:
            return page_route_path
        route_path = self._extract_route_path(signal)
        if route_path is not None and route_path in page_store:
            return route_path
        return None

    def _is_interaction_only_signal(
        self,
        *,
        signal: dict[str, Any],
        entry_candidates: list[dict[str, object]],
    ) -> bool:
        if not entry_candidates:
            return False
        if self._normalize_entry_type(signal.get("entry_type") or signal.get("interaction_type")) is not None:
            return True
        if self._normalize_entry_type(signal.get("interaction")) is not None:
            return True
        page_route_path = self._normalize_path(signal.get("page_route_path"))
        route_path = self._normalize_path(signal.get("route_path") or signal.get("path"))
        if page_route_path is not None and route_path is not None and page_route_path != route_path:
            return True
        return False

    def _merge_signal_to_page(
        self,
        *,
        page: "_PageStore",
        signal: dict[str, Any],
        entry_candidates: list[dict[str, object]],
        include_label_as_title: bool,
    ) -> None:
        title_candidate = self._clean_text(signal.get("page_title") or signal.get("title") or signal.get("name"))
        if title_candidate is None and include_label_as_title:
            title_candidate = self._clean_text(signal.get("label"))
        page.title = page.title or title_candidate
        page.sources.update(self._extract_sources(signal))
        context_constraints = self._to_dict(signal.get("context_constraints"))
        if context_constraints:
            page.context_constraints.update(context_constraints)
        for entry_candidate in entry_candidates:
            serialized = json.dumps(entry_candidate, ensure_ascii=False, sort_keys=True)
            if serialized in page.entry_keys:
                continue
            page.entry_keys.add(serialized)
            page.entry_candidates.append(entry_candidate)

    def _collect_extraction_hints(
        self,
        *,
        signal: dict[str, Any],
        quality_hints: list[float],
        framework_hints: list[str],
    ) -> None:
        quality_hint = signal.get("quality_score_hint")
        if isinstance(quality_hint, (int, float)):
            quality_hints.append(float(quality_hint))
        framework_hint = self._clean_text(signal.get("framework_hint"))
        if framework_hint is not None:
            framework_hints.append(framework_hint)

    def _to_entry_candidates(self, signal: dict[str, Any]) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        existing_entry_candidates = signal.get("entry_candidates")
        if isinstance(existing_entry_candidates, list):
            for candidate in existing_entry_candidates:
                if not isinstance(candidate, dict):
                    continue
                entry_type = self._normalize_entry_type(candidate.get("entry_type"))
                if entry_type is None:
                    continue
                normalized = dict(candidate)
                normalized["entry_type"] = entry_type
                candidates.append(normalized)
        if candidates:
            return candidates

        entry_type = self._normalize_entry_type(
            signal.get("entry_type")
            or signal.get("interaction_type")
            or signal.get("interaction")
            or signal.get("role")
        )
        if entry_type is None:
            return []
        label = self._clean_text(signal.get("label") or signal.get("text") or signal.get("name") or signal.get("title"))
        candidate: dict[str, object] = {"entry_type": entry_type}
        if label is not None:
            candidate["label"] = label
        return [candidate]

    def _normalize_entry_type(self, value: Any) -> str | None:
        clean_value = self._clean_text(value)
        if clean_value is None:
            return None
        normalized = clean_value.lower().replace("-", "_")
        if normalized in {"tab", "switch_tab"}:
            normalized = "tab_switch"
        if normalized in {"modal", "show_modal"}:
            normalized = "open_modal"
        if normalized in {"drawer", "show_drawer"}:
            normalized = "open_drawer"
        if normalized in {"expand_filter", "open_filter", "toggle_filter"}:
            normalized = "filter_expand"
        if normalized not in self._ENTRY_TYPES:
            return None
        return normalized

    def _extract_sources(self, signal: dict[str, Any]) -> set[str]:
        sources: set[str] = set()
        discovery_sources = signal.get("discovery_sources")
        if isinstance(discovery_sources, list):
            for item in discovery_sources:
                source = self._clean_text(item)
                if source is not None:
                    sources.add(source)
        source = self._clean_text(signal.get("source"))
        if source is not None:
            sources.add(source)
        return sources

    def _ensure_dict_list(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        records: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                records.append(item)
        return records

    def _to_dict(self, value: Any) -> dict[str, object] | None:
        if isinstance(value, dict):
            return value
        return None

    def _normalize_path(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        raw = value.strip()
        if not raw:
            return None

        parsed = urlparse(raw)
        path = parsed.path if parsed.scheme else raw.split("?", 1)[0].split("#", 1)[0]
        if not path.startswith("/"):
            return None
        return path.rstrip("/") or "/"

    def _clean_text(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        text = value.strip()
        return text or None


class _PageStore:
    def __init__(self) -> None:
        self.title: str | None = None
        self.sources: set[str] = set()
        self.entry_candidates: list[dict[str, object]] = []
        self.entry_keys: set[str] = set()
        self.context_constraints: dict[str, object] = {}


@dataclass(slots=True)
class _NavigationTargetSeed:
    target: NavigationTarget
    signal: dict[str, Any]
    entry_candidate: dict[str, object] | None
    include_label_as_title: bool


@dataclass(slots=True)
class _NavigationTargetGroup:
    target: NavigationTarget
    seeds: list[_NavigationTargetSeed] = field(default_factory=list)
