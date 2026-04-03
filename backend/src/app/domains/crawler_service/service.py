from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session, select

from app.domains.crawler_service.extractors.dom_menu import (
    DomMenuExtractor,
    DomMenuTraversalExtractor,
)
from app.domains.crawler_service.extractors.page_discovery import (
    PageDiscoveryExtractor,
    PageDiscoveryProtocol,
)
from app.domains.crawler_service.extractors.router_runtime import (
    RuntimeRouteHintExtractor,
    RouterRuntimeExtractor,
)
from app.domains.crawler_service.extractors.state_probe import (
    ControlledStateProbeExtractor,
    StateProbeExtractor,
)
from app.domains.crawler_service.schemas import (
    CrawlExtractionResult,
    CrawlRunResult,
    ElementCandidate,
    MenuCandidate,
    PageCandidate,
)
from app.infrastructure.db.models.crawl import CrawlSnapshot, MenuNode, Page, PageElement
from app.infrastructure.db.models.systems import AuthState, System
from app.shared.enums import AuthStateStatus


def utcnow() -> datetime:
    return datetime.now(UTC)


class BrowserSession(Protocol):
    framework_hint: str | None

    async def collect_route_hints(self, *, crawl_scope: str) -> list[dict[str, object]]: ...

    async def collect_dom_menu_nodes(self, *, crawl_scope: str) -> list[dict[str, object]]: ...

    async def collect_dom_elements(self, *, crawl_scope: str) -> list[dict[str, object]]: ...

    async def collect_network_route_configs(self, *, crawl_scope: str) -> list[dict[str, object]]: ...

    async def collect_network_resource_hints(self, *, crawl_scope: str) -> list[dict[str, object]]: ...

    async def collect_network_requests(self, *, crawl_scope: str) -> list[dict[str, object]]: ...

    async def collect_page_metadata(self, *, crawl_scope: str) -> list[dict[str, object]]: ...

    async def close(self) -> None: ...


class BrowserFactory(Protocol):
    async def open_context(
        self,
        *,
        base_url: str,
        storage_state: dict[str, object],
    ) -> BrowserSession: ...


class PlaywrightBrowserFactory:
    _INITIAL_SETTLE_MS = 5000
    _ROUTE_SETTLE_MS = 2000
    _ROUTE_RENDER_TIMEOUT_MS = 10000
    _ROUTE_HINTS_SCRIPT = """
() => {
  const __RUNLET_ROUTE_HINTS__ = true;
  const seen = new Set();
  const candidates = [];
  const pushCandidate = (path, title) => {
    if (typeof path !== "string") return;
    const cleanPath = path.trim();
    if (!cleanPath || !cleanPath.startsWith("/") || seen.has(cleanPath)) return;
    seen.add(cleanPath);
    candidates.push({
      path: cleanPath,
      title: typeof title === "string" ? title.trim() || null : null,
    });
  };

  pushCandidate(window.location.pathname, document.title);

  const nextDataPath = window.__NEXT_DATA__?.page;
  if (typeof nextDataPath === "string") {
    pushCandidate(nextDataPath, document.title);
  }

  const nuxtPath = window.__NUXT__?.data?.[0]?.routePath || window.__NUXT__?.routePath;
  if (typeof nuxtPath === "string") {
    pushCandidate(nuxtPath, document.title);
  }

  const statePath = window.__INITIAL_STATE__?.router?.location?.pathname;
  if (typeof statePath === "string") {
    pushCandidate(statePath, document.title);
  }

  const runtimeRouteTables = [
    window.__NEXT_DATA__?.props?.pageProps?.routes,
    window.__INITIAL_STATE__?.router?.routes,
    window.__VUE_ROUTER__?.options?.routes,
    window.$router?.options?.routes,
  ];

  for (const table of runtimeRouteTables) {
    if (!Array.isArray(table)) continue;
    for (const route of table) {
      if (!route || typeof route !== "object") continue;
      pushCandidate(route.path, route.meta?.title || route.name || route.title || null);
      if (Array.isArray(route.children)) {
        for (const child of route.children) {
          if (!child || typeof child !== "object") continue;
          pushCandidate(child.path, child.meta?.title || child.name || child.title || null);
        }
      }
    }
  }

  for (const node of Array.from(document.querySelectorAll("a[href], [data-route-path], [data-path]"))) {
    const raw = node.getAttribute("href")
      || node.getAttribute("data-route-path")
      || node.getAttribute("data-path");
    if (!raw) continue;
    try {
      const url = raw.startsWith("/") ? new URL(raw, window.location.origin) : new URL(raw, window.location.href);
      pushCandidate(url.pathname, node.textContent || node.getAttribute("aria-label"));
    } catch {
      continue;
    }
  }

  return candidates;
}
"""
    _MENU_NODES_SCRIPT = """
() => {
  const __RUNLET_MENU_NODES__ = true;
  const result = [];
  const selectors = [
    '[role="menuitem"]',
    'nav a',
    'aside a',
    '[data-menu-item]',
    '.menu a'
  ];
  const nodes = document.querySelectorAll(selectors.join(','));
  Array.from(nodes).forEach((node, index) => {
    const text = (node.textContent || node.getAttribute('aria-label') || '').trim();
    if (!text) return;
    const href = node.getAttribute('href');
    let routePath = null;
    if (href) {
      try {
        routePath = new URL(href, window.location.origin).pathname;
      } catch {
        routePath = null;
      }
    }
    const parentMenu = node.closest('[role="menu"], nav, aside');
    const depth = parentMenu ? parentMenu.querySelectorAll('[role="menu"], ul, ol').length - 1 : 0;
    result.push({
      label: text,
      route_path: routePath,
      page_route_path: routePath,
      depth: depth > 0 ? depth : 0,
      order: index,
      role: node.getAttribute('role') || 'menuitem',
      aria_label: node.getAttribute('aria-label'),
    });
  });
  return result;
}
"""
    _DOM_ELEMENTS_SCRIPT = """
() => {
  const __RUNLET_PAGE_ELEMENTS__ = true;
  const result = [];
  const isVisible = (node) => {
    if (!(node instanceof Element)) return false;
    const style = window.getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return style.visibility !== 'hidden'
      && style.display !== 'none'
      && rect.width > 0
      && rect.height > 0;
  };
  const selectors = [
    'button',
    '[role="button"]',
    'input',
    'select',
    'textarea',
    'table',
    '[role="grid"]',
    '.el-table',
    '.vxe-table',
    '.ant-table',
    '.ivu-table',
    '.n-data-table',
    '.ag-root',
    '[class*="ag-theme"]',
    '[role="tab"]',
    '[role="searchbox"]',
    '[data-testid]'
  ];
  const nodes = document.querySelectorAll(selectors.join(','));
  Array.from(nodes).forEach((node) => {
    if (!isVisible(node)) return;
    const tagName = (node.tagName || '').toLowerCase();
    const role = node.getAttribute('role');
    const text = (node.textContent || node.getAttribute('aria-label') || node.getAttribute('placeholder') || '').trim();
    const className = typeof node.className === 'string' ? node.className : '';
    const isTableLike = tagName === 'table'
      || role === 'grid'
      || role === 'table'
      || className.includes('el-table')
      || className.includes('vxe-table')
      || className.includes('ant-table')
      || className.includes('ivu-table')
      || className.includes('n-data-table')
      || className.includes('ag-root')
      || className.includes('ag-theme');
    const elementType = role === 'tab'
      ? 'tab'
      : isTableLike
      ? 'table'
      : tagName || role || 'element';
    if (!elementType) return;
    result.push({
      page_route_path: window.location.pathname,
      element_type: elementType,
      role: role || null,
      text: text || null,
      aria_label: node.getAttribute('aria-label'),
      class_name: className || null,
      visible: true,
      attributes: {
        name: node.getAttribute('name'),
        type: node.getAttribute('type'),
        placeholder: node.getAttribute('placeholder'),
        data_testid: node.getAttribute('data-testid'),
      },
      usage_description: text || null,
    });
  });
  return result;
}
"""
    _ROUTE_RENDER_READY_SCRIPT = """
() => {
  const visibleSelector = (selector) => {
    return Array.from(document.querySelectorAll(selector)).some((node) => {
      const style = window.getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      return style.visibility !== 'hidden'
        && style.display !== 'none'
        && rect.width > 0
        && rect.height > 0;
    });
  };
  const bodyText = (document.body?.innerText || '').trim();
  return bodyText.length > 50
    || visibleSelector('table, [role="grid"], .el-table, .vxe-table, .ant-table, .ivu-table, .n-data-table, .ag-root, [class*="ag-theme"]');
}
"""
    _NETWORK_ROUTE_CONFIGS_SCRIPT = """
() => {
  const __RUNLET_NETWORK_ROUTE_CONFIGS__ = true;
  const seen = new Set();
  const result = [];
  const pushRoute = (value, source) => {
    if (typeof value !== 'string') return;
    const route = value.trim();
    if (!route || !route.startsWith('/') || seen.has(route)) return;
    seen.add(route);
    result.push({ route_path: route, source });
  };

  const routeTables = [
    window.__NEXT_DATA__?.props?.pageProps?.routes,
    window.__INITIAL_STATE__?.router?.routes,
    window.__VUE_ROUTER__?.options?.routes,
    window.$router?.options?.routes,
  ];

  for (const table of routeTables) {
    if (!Array.isArray(table)) continue;
    for (const route of table) {
      if (!route || typeof route !== 'object') continue;
      pushRoute(route.path, 'network_route_config');
      if (Array.isArray(route.children)) {
        for (const child of route.children) {
          if (!child || typeof child !== 'object') continue;
          pushRoute(child.path, 'network_route_config');
        }
      }
    }
  }

  return result;
}
"""
    _NETWORK_RESOURCE_HINTS_SCRIPT = """
() => {
  const __RUNLET_NETWORK_RESOURCES__ = true;
  const seen = new Set();
  const result = [];
  const routeLike = (path) => {
    if (!path || !path.startsWith('/')) return false;
    if (path.startsWith('/api/')) return false;
    return !/\\.(js|mjs|css|png|jpe?g|svg|gif|ico|woff2?|map|json)(\\?.*)?$/i.test(path);
  };
  const pushPath = (raw) => {
    if (typeof raw !== 'string' || !raw) return;
    try {
      const url = raw.startsWith('/') ? new URL(raw, window.location.origin) : new URL(raw, window.location.href);
      const path = url.pathname;
      if (!routeLike(path) || seen.has(path)) return;
      seen.add(path);
      result.push({ route_path: path, source: 'network_resource' });
    } catch {
      return;
    }
  };

  for (const entry of performance.getEntriesByType('resource')) {
    if (!entry || typeof entry.name !== 'string') continue;
    pushPath(entry.name);
  }

  const preloadNodes = document.querySelectorAll("link[rel='prefetch'][href], link[rel='prerender'][href], link[rel='preload'][href]");
  for (const node of Array.from(preloadNodes)) {
    pushPath(node.getAttribute('href'));
  }

  return result;
}
"""
    _NETWORK_REQUESTS_SCRIPT = """
() => {
  const __RUNLET_NETWORK_REQUESTS__ = true;
  const seen = new Set();
  const result = [];
  const routeLike = (path) => {
    if (!path || !path.startsWith('/')) return false;
    if (path.startsWith('/api/')) return false;
    return !/\\.(js|mjs|css|png|jpe?g|svg|gif|ico|woff2?|map|json)(\\?.*)?$/i.test(path);
  };
  const pushPath = (raw) => {
    if (typeof raw !== 'string' || !raw) return;
    try {
      const url = raw.startsWith('/') ? new URL(raw, window.location.origin) : new URL(raw, window.location.href);
      const path = url.pathname;
      if (!routeLike(path) || seen.has(path)) return;
      seen.add(path);
      result.push({ path, source: 'network_request' });
    } catch {
      return;
    }
  };

  for (const entry of performance.getEntriesByType('resource')) {
    if (!entry || typeof entry.name !== 'string') continue;
    if (entry.initiatorType !== 'fetch' && entry.initiatorType !== 'xmlhttprequest' && entry.initiatorType !== 'beacon') {
      continue;
    }
    pushPath(entry.name);
  }

  return result;
}
"""
    _PAGE_METADATA_SCRIPT = """
() => {
  const __RUNLET_PAGE_METADATA__ = true;
  const path = typeof window.location.pathname === "string" ? window.location.pathname.trim() : "";
  if (!path || !path.startsWith("/")) {
    return [];
  }

  const navEntry = performance.getEntriesByType("navigation")[0];
  let statusCode = null;
  if (navEntry && typeof navEntry.responseStatus === "number" && Number.isFinite(navEntry.responseStatus)) {
    statusCode = navEntry.responseStatus;
  }

  return [
    {
      route_path: path,
      page_title: typeof document.title === "string" ? document.title.trim() || null : null,
      reachable: true,
      status_code: statusCode,
    },
  ];
}
"""

    async def open_context(
        self,
        *,
        base_url: str,
        storage_state: dict[str, object],
    ) -> BrowserSession:
        try:
            from playwright.async_api import async_playwright
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise RuntimeError("playwright is not installed") from exc

        playwright = await async_playwright().start()  # pragma: no cover
        browser = await playwright.chromium.launch(headless=True)  # pragma: no cover
        context = await browser.new_context(  # pragma: no cover
            base_url=base_url,
            storage_state=storage_state,
        )
        page = await context.new_page()  # pragma: no cover
        await page.goto(base_url, wait_until="domcontentloaded")  # pragma: no cover

        class _Session:
            framework_hint = None
            _settled = False

            async def _ensure_settled(self_nonlocal) -> None:
                if self_nonlocal._settled:
                    return
                await page.wait_for_timeout(PlaywrightBrowserFactory._INITIAL_SETTLE_MS)
                self_nonlocal._settled = True

            async def collect_route_hints(
                self_nonlocal,
                *,
                crawl_scope: str,
            ) -> list[dict[str, object]]:
                del crawl_scope
                await self_nonlocal._ensure_settled()
                return await page.evaluate(PlaywrightBrowserFactory._ROUTE_HINTS_SCRIPT)

            async def collect_dom_menu_nodes(
                self_nonlocal,
                *,
                crawl_scope: str,
            ) -> list[dict[str, object]]:
                del crawl_scope
                await self_nonlocal._ensure_settled()
                return await page.evaluate(PlaywrightBrowserFactory._MENU_NODES_SCRIPT)

            async def collect_dom_elements(
                self_nonlocal,
                *,
                crawl_scope: str,
            ) -> list[dict[str, object]]:
                await self_nonlocal._ensure_settled()
                route_hints = await page.evaluate(PlaywrightBrowserFactory._ROUTE_HINTS_SCRIPT)
                menu_nodes = await page.evaluate(PlaywrightBrowserFactory._MENU_NODES_SCRIPT)
                route_paths: list[str] = []
                seen_routes: set[str] = set()

                def add_route(route_path: object) -> None:
                    if not isinstance(route_path, str):
                        return
                    normalized = route_path.strip()
                    if not normalized or not normalized.startswith("/") or normalized in seen_routes:
                        return
                    seen_routes.add(normalized)
                    route_paths.append(normalized)

                if crawl_scope == "full":
                    for hint in route_hints:
                        if isinstance(hint, dict):
                            add_route(hint.get("path") or hint.get("route_path"))
                    for node in menu_nodes:
                        if isinstance(node, dict):
                            add_route(node.get("route_path") or node.get("page_route_path"))
                else:
                    current_path = await page.evaluate("() => window.location.pathname")
                    add_route(current_path)

                if not route_paths:
                    current_path = await page.evaluate("() => window.location.pathname")
                    add_route(current_path)

                elements: list[dict[str, object]] = []
                seen_payloads: set[str] = set()
                for route_path in route_paths:
                    await page.goto(f"{base_url.rstrip('/')}{route_path}", wait_until="domcontentloaded")
                    await self_nonlocal._wait_for_route_render()
                    await page.wait_for_timeout(PlaywrightBrowserFactory._ROUTE_SETTLE_MS)
                    collected = await page.evaluate(PlaywrightBrowserFactory._DOM_ELEMENTS_SCRIPT)
                    if not isinstance(collected, list):
                        continue
                    for item in collected:
                        if not isinstance(item, dict):
                            continue
                        payload = dict(item)
                        if not payload.get("page_route_path"):
                            payload["page_route_path"] = route_path
                        dedupe_key = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                        if dedupe_key in seen_payloads:
                            continue
                        seen_payloads.add(dedupe_key)
                        elements.append(payload)
                return elements

            async def collect_network_route_configs(
                self_nonlocal,
                *,
                crawl_scope: str,
            ) -> list[dict[str, object]]:
                del crawl_scope
                await self_nonlocal._ensure_settled()
                collected = await page.evaluate(PlaywrightBrowserFactory._NETWORK_ROUTE_CONFIGS_SCRIPT)
                if isinstance(collected, list):
                    return [item for item in collected if isinstance(item, dict)]
                return []

            async def collect_network_resource_hints(
                self_nonlocal,
                *,
                crawl_scope: str,
            ) -> list[dict[str, object]]:
                del crawl_scope
                await self_nonlocal._ensure_settled()
                collected = await page.evaluate(PlaywrightBrowserFactory._NETWORK_RESOURCE_HINTS_SCRIPT)
                if isinstance(collected, list):
                    return [item for item in collected if isinstance(item, dict)]
                return []

            async def collect_network_requests(
                self_nonlocal,
                *,
                crawl_scope: str,
            ) -> list[dict[str, object]]:
                del crawl_scope
                await self_nonlocal._ensure_settled()
                collected = await page.evaluate(PlaywrightBrowserFactory._NETWORK_REQUESTS_SCRIPT)
                if isinstance(collected, list):
                    return [item for item in collected if isinstance(item, dict)]
                return []

            async def collect_page_metadata(
                self_nonlocal,
                *,
                crawl_scope: str,
            ) -> list[dict[str, object]]:
                del crawl_scope
                await self_nonlocal._ensure_settled()
                collected = await page.evaluate(PlaywrightBrowserFactory._PAGE_METADATA_SCRIPT)
                if isinstance(collected, list):
                    return [item for item in collected if isinstance(item, dict)]
                return []

            async def _wait_for_route_render(self_nonlocal) -> None:
                waiter = getattr(page, "wait_for_function", None)
                if not callable(waiter):
                    return
                try:
                    if await page.evaluate(PlaywrightBrowserFactory._ROUTE_RENDER_READY_SCRIPT):
                        return
                    await waiter(
                        PlaywrightBrowserFactory._ROUTE_RENDER_READY_SCRIPT,
                        timeout=PlaywrightBrowserFactory._ROUTE_RENDER_TIMEOUT_MS,
                    )
                except Exception:
                    return

            async def close(self_nonlocal) -> None:
                await page.close()
                await context.close()
                await browser.close()
                await playwright.stop()

        return _Session()


class CrawlerService:
    def __init__(
        self,
        *,
        session: Session | AsyncSession,
        browser_factory: BrowserFactory,
        page_discovery_extractor: PageDiscoveryProtocol | None = None,
        router_extractor: RouterRuntimeExtractor | None = None,
        dom_menu_extractor: DomMenuExtractor | None = None,
        state_probe_extractor: StateProbeExtractor | None = None,
    ) -> None:
        self.session = session
        self.browser_factory = browser_factory
        self.router_extractor = router_extractor or RuntimeRouteHintExtractor()
        self.dom_menu_extractor = dom_menu_extractor or DomMenuTraversalExtractor()
        discovery_dom_extractor = self.dom_menu_extractor
        if not callable(getattr(discovery_dom_extractor, "collect_navigation_signals", None)):
            discovery_dom_extractor = None
        self.page_discovery_extractor = page_discovery_extractor or PageDiscoveryExtractor(
            runtime_extractor=self.router_extractor,
            dom_menu_extractor=discovery_dom_extractor,
        )
        self.state_probe_extractor = state_probe_extractor or ControlledStateProbeExtractor()

    async def run_crawl(
        self,
        *,
        system_id: UUID,
        crawl_scope: str,
    ) -> CrawlRunResult:
        system = await self._get(System, system_id)
        if system is None:
            return CrawlRunResult(
                system_id=system_id,
                status="failed",
                message="system not found",
            )

        auth_state = await self._load_latest_valid_auth_state(system_id=system_id)
        if auth_state is None or not auth_state.storage_state:
            return CrawlRunResult(system_id=system_id, status="auth_required")

        browser_session = await self.browser_factory.open_context(
            base_url=system.base_url,
            storage_state=auth_state.storage_state,
        )

        try:
            page_discovery_result = await self.page_discovery_extractor.extract(
                browser_session=browser_session,
                system=system,
                crawl_scope=crawl_scope,
            )
            dom_result = await self.dom_menu_extractor.extract(
                browser_session=browser_session,
                system=system,
                crawl_scope=crawl_scope,
            )
            probe_result = await self.state_probe_extractor.extract(
                browser_session=browser_session,
                system=system,
                crawl_scope=crawl_scope,
            )
        finally:
            await browser_session.close()

        combined = self._combine_results(
            system=system,
            discovery=page_discovery_result,
            dom=dom_result,
            probe=probe_result,
        )
        snapshot = self._build_snapshot(
            system_id=system_id,
            crawl_scope=crawl_scope,
            system_framework=system.framework_type,
            extraction=combined,
        )
        self.session.add(snapshot)
        await self._flush()

        page_map = await self._persist_pages(
            system_id=system_id,
            snapshot_id=snapshot.id,
            pages=combined.pages,
        )
        await self._persist_menus(
            system_id=system_id,
            snapshot_id=snapshot.id,
            menus=combined.menus,
            page_map=page_map,
        )
        await self._persist_elements(
            system_id=system_id,
            snapshot_id=snapshot.id,
            elements=combined.elements,
            page_map=page_map,
        )

        snapshot.finished_at = utcnow()
        await self._commit()

        return CrawlRunResult(
            system_id=system_id,
            status="success",
            snapshot_id=snapshot.id,
            pages_saved=len(page_map),
            menus_saved=len(combined.menus),
            elements_saved=len(combined.elements),
            failure_reason=combined.failure_reason,
            warning_messages=combined.warning_messages,
            degraded=combined.degraded,
        )

    def _combine_results(
        self,
        *,
        system,
        discovery: CrawlExtractionResult,
        dom: CrawlExtractionResult,
        probe: CrawlExtractionResult,
    ) -> CrawlExtractionResult:
        representative_elements = probe.elements or [item for item in dom.elements if item.state_signature]
        page_candidates: dict[str, PageCandidate] = {}
        for candidate in discovery.pages + dom.pages + probe.pages:
            page_candidates[candidate.route_path] = candidate

        title_route_map = self._build_title_route_map(page_candidates.values())

        normalized_dom_menus: list[MenuCandidate] = []
        for menu in dom.menus:
            route_path = menu.route_path
            page_route_path = menu.page_route_path
            if route_path is None:
                route_path = title_route_map.get(self._normalize_title_key(menu.label))
            if page_route_path is None:
                page_route_path = route_path
            normalized_dom_menus.append(
                menu.model_copy(
                    update={
                        "route_path": route_path,
                        "page_route_path": page_route_path,
                    }
                )
            )

        for menu in normalized_dom_menus:
            route_path = menu.page_route_path or menu.route_path
            if route_path and route_path not in page_candidates:
                page_candidates[route_path] = PageCandidate(route_path=route_path, page_title=menu.label)

        for element in representative_elements:
            if element.page_route_path not in page_candidates:
                page_candidates[element.page_route_path] = PageCandidate(route_path=element.page_route_path)

        quality_candidates = [
            value for value in (discovery.quality_score, dom.quality_score, probe.quality_score) if value is not None
        ]
        quality_score = max(quality_candidates) if quality_candidates else None
        failure_reason = discovery.failure_reason or dom.failure_reason or probe.failure_reason
        warning_messages = [*discovery.warning_messages, *dom.warning_messages, *probe.warning_messages]
        degraded = discovery.degraded or dom.degraded or len(page_candidates) == 0

        return CrawlExtractionResult(
            framework_detected=(
                discovery.framework_detected
                or probe.framework_detected
                or dom.framework_detected
                or system.framework_type
            ),
            quality_score=quality_score,
            pages=list(page_candidates.values()),
            menus=normalized_dom_menus,
            elements=representative_elements,
            failure_reason=failure_reason,
            warning_messages=warning_messages,
            degraded=degraded,
        )

    def _build_title_route_map(self, pages: list[PageCandidate] | object) -> dict[str, str]:
        title_route_map: dict[str, str] = {}
        for page in pages:
            if not isinstance(page, PageCandidate):
                continue
            if page.page_title is None:
                continue
            normalized_title = self._normalize_title_key(page.page_title)
            if normalized_title and normalized_title not in title_route_map:
                title_route_map[normalized_title] = page.route_path
        return title_route_map

    def _normalize_title_key(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        for separator in ("_", "|", "-", "—"):
            if separator in normalized:
                normalized = normalized.split(separator, 1)[0].strip()
        return normalized or None

    def _build_snapshot(
        self,
        *,
        system_id: UUID,
        crawl_scope: str,
        system_framework: str,
        extraction: CrawlExtractionResult,
    ) -> CrawlSnapshot:
        page_routes = sorted(candidate.route_path for candidate in extraction.pages)
        structure_hash = hashlib.sha256(
            json.dumps(page_routes, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return CrawlSnapshot(
            system_id=system_id,
            crawl_type=crawl_scope,
            framework_detected=extraction.framework_detected or system_framework,
            quality_score=extraction.quality_score,
            degraded=extraction.degraded,
            failure_reason=extraction.failure_reason,
            warning_messages=extraction.warning_messages,
            structure_hash=structure_hash,
        )

    async def _persist_pages(
        self,
        *,
        system_id: UUID,
        snapshot_id: UUID,
        pages: list[PageCandidate],
    ) -> dict[str, Page]:
        page_map: dict[str, Page] = {}
        for candidate in pages:
            page = Page(
                system_id=system_id,
                snapshot_id=snapshot_id,
                route_path=candidate.route_path,
                page_title=candidate.page_title,
                page_summary=candidate.page_summary,
                keywords=candidate.keywords,
                discovery_sources=candidate.discovery_sources,
                entry_candidates=candidate.entry_candidates,
                context_constraints=candidate.context_constraints,
            )
            self.session.add(page)
            await self._flush()
            page_map[candidate.route_path] = page
        return page_map

    async def _persist_menus(
        self,
        *,
        system_id: UUID,
        snapshot_id: UUID,
        menus: list[MenuCandidate],
        page_map: dict[str, Page],
    ) -> None:
        label_map: dict[str, MenuNode] = {}
        for candidate in menus:
            page = page_map.get(candidate.page_route_path or candidate.route_path or "")
            parent = label_map.get(candidate.parent_label or "")
            menu = MenuNode(
                system_id=system_id,
                snapshot_id=snapshot_id,
                parent_id=parent.id if parent else None,
                page_id=page.id if page else None,
                label=candidate.label,
                route_path=candidate.route_path,
                depth=candidate.depth,
                sort_order=candidate.sort_order,
                playwright_locator=candidate.playwright_locator,
                discovery_sources=candidate.discovery_sources,
                entry_candidates=candidate.entry_candidates,
                context_constraints=candidate.context_constraints,
            )
            self.session.add(menu)
            await self._flush()
            label_map[candidate.label] = menu

    async def _persist_elements(
        self,
        *,
        system_id: UUID,
        snapshot_id: UUID,
        elements: list[ElementCandidate],
        page_map: dict[str, Page],
    ) -> None:
        for candidate in elements:
            page = page_map.get(candidate.page_route_path)
            if page is None:
                continue
            element = PageElement(
                system_id=system_id,
                snapshot_id=snapshot_id,
                page_id=page.id,
                element_type=candidate.element_type,
                element_role=candidate.element_role,
                element_text=candidate.element_text,
                attributes=candidate.attributes,
                playwright_locator=candidate.playwright_locator,
                state_signature=candidate.state_signature,
                state_context=candidate.state_context,
                locator_candidates=candidate.locator_candidates,
                stability_score=candidate.stability_score,
                usage_description=candidate.usage_description,
            )
            self.session.add(element)
            await self._flush()

    async def _load_latest_valid_auth_state(self, *, system_id: UUID) -> AuthState | None:
        statement = (
            select(AuthState)
            .where(AuthState.system_id == system_id)
            .where(AuthState.status == AuthStateStatus.VALID.value)
            .where(AuthState.is_valid.is_(True))
            .order_by(AuthState.validated_at.desc(), AuthState.id.desc())
        )
        return await self._exec_first(statement)

    async def _exec_first(self, statement):
        if isinstance(self.session, AsyncSession):
            result = await self.session.exec(statement)
            return result.first()
        return self.session.exec(statement).first()

    async def _get(self, model, identifier):
        if isinstance(self.session, AsyncSession):
            return await self.session.get(model, identifier)
        return self.session.get(model, identifier)

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
