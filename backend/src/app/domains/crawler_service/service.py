from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session, select

from app.domains.crawler_service.extractors.app_readiness import evaluate_app_readiness
from app.domains.crawler_service.extractors.dom_menu import (
    DomMenuExtractor,
    DomMenuTraversalExtractor,
    build_menu_expand_targets,
    merge_menu_skeleton_and_materialized_nodes,
)
from app.domains.crawler_service.extractors.page_discovery import (
    PageDiscoveryExtractor,
    PageDiscoveryProtocol,
)
from app.domains.crawler_service.extractors.router_runtime import (
    RuntimeRouteHintExtractor,
    RouterRuntimeExtractor,
)
from app.domains.crawler_service.extractors.route_resolution import resolve_route_snapshot
from app.domains.crawler_service.extractors.state_probe import (
    ControlledStateProbeExtractor,
    StateProbeExtractor,
    build_navigation_action_payload,
)
from app.domains.crawler_service.schemas import (
    ALLOWED_STATE_PROBE_ACTIONS,
    CrawlExtractionResult,
    CrawlRunResult,
    ElementCandidate,
    MenuCandidate,
    PageCandidate,
)
from app.infrastructure.db.models.crawl import CrawlSnapshot, MenuNode, Page, PageElement
from app.infrastructure.db.models.systems import AuthState, System, SystemCredential
from app.shared.enums import AuthStateStatus


def utcnow() -> datetime:
    return datetime.now(UTC)


def _derive_crawl_entry_url(*, base_url: str, login_url: str | None) -> str:
    normalized_base_url = base_url.strip()
    if not normalized_base_url:
        return base_url
    if not login_url or not isinstance(login_url, str) or not login_url.strip():
        return normalized_base_url

    try:
        resolved_login_url = urljoin(normalized_base_url.rstrip("/") + "/", login_url.strip())
        parsed_base = urlparse(normalized_base_url)
        parsed_login = urlparse(resolved_login_url)
    except Exception:
        return normalized_base_url

    if not parsed_login.scheme or not parsed_login.netloc:
        return normalized_base_url

    login_path = parsed_login.path or parsed_base.path or "/"
    login_fragment = (parsed_login.fragment or "").strip()
    fragment_path, _, fragment_query = login_fragment.partition("?")
    redirect_candidates = [
        *parse_qs(parsed_login.query).get("redirect", []),
        *parse_qs(fragment_query).get("redirect", []),
    ]

    redirect_path = next(
        (
            candidate.strip()
            for candidate in redirect_candidates
            if isinstance(candidate, str) and candidate.strip().startswith("/")
        ),
        None,
    )
    fragment_route = fragment_path.strip() if fragment_path.strip().startswith("/") else None
    login_markers = {"login", "signin", "sign-in"}

    def _looks_like_login(value: str | None) -> bool:
        if value is None:
            return False
        lowered = value.lower()
        return any(marker in lowered for marker in login_markers)

    if redirect_path is not None and login_fragment:
        return urlunparse(
            (
                parsed_login.scheme,
                parsed_login.netloc,
                login_path,
                "",
                "",
                redirect_path,
            )
        )

    if fragment_route is not None and not _looks_like_login(fragment_route):
        return urlunparse(
            (
                parsed_login.scheme,
                parsed_login.netloc,
                login_path,
                "",
                "",
                fragment_route,
            )
        )

    if redirect_path is not None:
        redirect_url = urljoin(
            urlunparse((parsed_login.scheme, parsed_login.netloc, login_path, "", "", "")),
            redirect_path,
        )
        parsed_redirect = urlparse(redirect_url)
        return urlunparse(
            (
                parsed_redirect.scheme,
                parsed_redirect.netloc,
                parsed_redirect.path or "/",
                "",
                "",
                "",
            )
        )

    if login_path and login_path != "/" and not _looks_like_login(login_path):
        return urlunparse(
            (
                parsed_login.scheme,
                parsed_login.netloc,
                login_path,
                "",
                "",
                "",
            )
        )

    return normalized_base_url


class BrowserSession(Protocol):
    framework_hint: str | None

    async def collect_route_hints(self, *, crawl_scope: str) -> list[dict[str, object]]: ...
    async def collect_route_snapshot(self, *, crawl_scope: str) -> dict[str, object]: ...

    async def collect_dom_menu_skeleton(self, *, crawl_scope: str) -> list[dict[str, object]]: ...
    async def collect_dom_menu_nodes(self, *, crawl_scope: str) -> list[dict[str, object]]: ...
    async def materialize_navigation_targets(
        self,
        *,
        targets: list[dict[str, object]],
        crawl_scope: str,
    ) -> list[dict[str, object]]: ...

    async def collect_dom_elements(self, *, crawl_scope: str) -> list[dict[str, object]]: ...

    async def collect_network_route_configs(self, *, crawl_scope: str) -> list[dict[str, object]]: ...

    async def collect_network_resource_hints(self, *, crawl_scope: str) -> list[dict[str, object]]: ...

    async def collect_network_requests(self, *, crawl_scope: str) -> list[dict[str, object]]: ...

    async def collect_page_metadata(self, *, crawl_scope: str) -> list[dict[str, object]]: ...

    async def collect_state_probe_baseline(self, *, crawl_scope: str) -> list[dict[str, object]]: ...

    async def collect_state_probe_actions(self, *, crawl_scope: str) -> list[dict[str, object]]: ...

    async def visit_page_target(
        self,
        *,
        page_target: dict[str, object],
        crawl_scope: str,
    ) -> dict[str, object]: ...

    async def perform_navigation_target(
        self,
        *,
        target: dict[str, object],
        page_context: dict[str, object],
        crawl_scope: str,
    ) -> dict[str, object]: ...

    async def perform_state_probe_action(
        self,
        *,
        action: dict[str, object],
        crawl_scope: str,
    ) -> dict[str, object]: ...

    async def close(self) -> None: ...


class BrowserFactory(Protocol):
    async def open_context(
        self,
        *,
        base_url: str,
        storage_state: dict[str, object],
        entry_url: str | None = None,
    ) -> BrowserSession: ...


class PlaywrightBrowserFactory:
    _INITIAL_SETTLE_MS = 5000
    _ROUTE_SETTLE_MS = 2000
    _ROUTE_RENDER_TIMEOUT_MS = 10000
    _APP_READINESS_WINDOW = 2
    _APP_READINESS_MAX_SAMPLES = 4
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
    _ROUTE_RUNTIME_SNAPSHOT_SCRIPT = """
() => {
  const __RUNLET_ROUTE_SNAPSHOT__ = true;
  const toRoute = (value) => {
    if (typeof value !== "string") return null;
    const trimmed = value.trim();
    return trimmed || null;
  };
  const hash = toRoute(window.location.hash);
  const routerCurrent = toRoute(
    window.__NEXT_DATA__?.page
      || window.__INITIAL_STATE__?.router?.location?.pathname
      || window.__VUE_ROUTER__?.currentRoute?.value?.path
      || window.__VUE_ROUTER__?.currentRoute?.path
      || window.$router?.currentRoute?.value?.path
      || window.$router?.currentRoute?.path
  );
  const historyRoute = toRoute(window.history.state?.as || window.history.state?.url || window.history.state?.path);
  return {
    pathname: toRoute(window.location.pathname),
    location_hash: hash,
    router_route: routerCurrent,
    history_route: historyRoute,
  };
}
"""
    _MENU_NODES_SCRIPT = """
() => {
  const __RUNLET_MENU_NODES__ = true;
  const normalizeText = (value) => {
    if (typeof value !== "string") return "";
    return value.replace(/\\s+/g, " ").trim();
  };
  const isVisible = (node) => {
    if (!(node instanceof Element)) return false;
    const style = window.getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return style.visibility !== "hidden"
      && style.display !== "none"
      && rect.width > 0
      && rect.height > 0;
  };
  const toLabel = (node) => normalizeText(
    node?.getAttribute?.("data-menu-label")
      || node?.getAttribute?.("aria-label")
      || node?.textContent
      || ""
  );
  const toRoutePath = (value) => {
    if (typeof value !== "string") return null;
    const trimmed = value.trim();
    if (!trimmed) return null;
    try {
      return new URL(trimmed, window.location.href).pathname || null;
    } catch {
      return trimmed.startsWith("/") ? trimmed : null;
    }
  };
  const hasCollapsedMenuMarker = (node) => {
    if (!(node instanceof Element)) return false;
    return Boolean(node.querySelector(".n-menu-item-content--collapsed"));
  };
  const itemSelectors = '[role="menuitem"], [role="treeitem"], .ant-menu-submenu, .el-submenu, .tree-node, li';
  const nodeSelectors = [
    '[role="menuitem"]',
    '[role="treeitem"]',
    'nav a',
    'aside a',
    '[data-menu-item]',
    '[data-route-path]',
    '[data-path]',
    '.menu a',
    '.ant-menu-submenu-title',
    '.el-submenu__title',
    '.el-menu-item',
    '.tree-node',
    '.el-tree-node__content'
  ];
  const parentLabelFor = (node) => {
    let current = node?.parentElement || null;
    while (current) {
      if (current.matches?.(itemSelectors)) {
        const label = toLabel(
          current.querySelector?.(
            '.ant-menu-submenu-title, .el-submenu__title, .tree-node__label, [role="menuitem"], [role="treeitem"], a, span'
          ) || current
        );
        if (label && label !== toLabel(node)) return label;
      }
      current = current.parentElement;
    }
    return null;
  };
  const inferredDepthFromIndent = (node) => {
    if (!(node instanceof Element)) return 0;
    const contentNode = node.querySelector(".n-menu-item-content") || node;
    const paddingLeft = Number.parseFloat(window.getComputedStyle(contentNode).paddingLeft || "0");
    if (!Number.isFinite(paddingLeft) || paddingLeft <= 0) return 0;
    return Math.max(0, Math.round(paddingLeft / 24) - 1);
  };
  const depthFor = (node) => {
    let depth = 0;
    let current = node?.parentElement || null;
    while (current) {
      if (current.matches?.(itemSelectors)) depth += 1;
      current = current.parentElement;
    }
    return Math.max(0, depth, inferredDepthFromIndent(node));
  };
  const result = [];
  const seen = new Set();
  const siblingCounts = new Map();
  const nodes = document.querySelectorAll(nodeSelectors.join(','));
  Array.from(nodes).forEach((node, index) => {
    if (!isVisible(node)) return;
    const text = toLabel(node);
    if (!text) return;
    const href = node.getAttribute('href')
      || node.getAttribute('data-route-path')
      || node.getAttribute('data-path');
    const routePath = toRoutePath(href);
    const role = node.getAttribute('role') || 'menuitem';
    const ariaExpanded = node.getAttribute('aria-expanded');
    const className = normalizeText(node.className);
    let entryType = normalizeText(
      node.getAttribute('data-entry-type') || node.getAttribute('data-interaction-type')
    ).replace(/-/g, '_') || null;
    if (!entryType && role === 'treeitem' && ariaExpanded === 'false') {
      entryType = 'tree_expand';
    }
    if (!entryType && (
      ariaExpanded === 'false'
      || className.includes('submenu')
      || className.includes('sub-menu')
      || className.includes('subnav')
      || className.includes('n-menu-item-content--collapsed')
      || hasCollapsedMenuMarker(node)
    )) {
      entryType = 'menu_expand';
    }
    const parentLabel = parentLabelFor(node);
    const depth = depthFor(node);
    const ariaLabel = node.getAttribute('aria-label');
    const siblingKey = JSON.stringify([text, parentLabel, depth, role, ariaLabel || null]);
    const siblingIndex = siblingCounts.get(siblingKey) || 0;
    siblingCounts.set(siblingKey, siblingIndex + 1);
    const dedupeKey = JSON.stringify([text, routePath, parentLabel, depth, role, ariaLabel || null, siblingIndex]);
    if (seen.has(dedupeKey)) return;
    seen.add(dedupeKey);
    result.push({
      label: text,
      route_path: routePath,
      page_route_path: routePath,
      depth,
      order: index,
      role,
      aria_label: ariaLabel,
      sibling_index: siblingIndex,
      parent_label: parentLabel,
      entry_type: entryType,
      aria_expanded: ariaExpanded,
    });
  });
  const depthStack = [];
  for (const item of result) {
    if (!item.parent_label && item.depth > 0) {
      const parent = depthStack[item.depth - 1];
      if (parent && parent.label) item.parent_label = parent.label;
    }
    depthStack[item.depth] = item;
    depthStack.length = item.depth + 1;
  }
  return result;
}
"""
    _CLICK_NAVIGATION_TARGET_SCRIPT = """
async (target) => {
  const __RUNLET_CLICK_NAVIGATION_TARGET__ = true;
  const normalizeText = (value) => {
    if (typeof value !== "string") return "";
    return value.replace(/\\s+/g, " ").trim();
  };
  const isVisible = (node) => {
    if (!(node instanceof Element)) return false;
    const style = window.getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return style.visibility !== "hidden"
      && style.display !== "none"
      && rect.width > 0
      && rect.height > 0;
  };
  const toLabel = (node) => normalizeText(
    node?.getAttribute?.("data-menu-label")
      || node?.getAttribute?.("aria-label")
      || node?.textContent
      || ""
  );
  const toRoutePath = (value) => {
    if (typeof value !== "string") return null;
    const trimmed = value.trim();
    if (!trimmed) return null;
    try {
      return new URL(trimmed, window.location.href).pathname || null;
    } catch {
      return trimmed.startsWith("/") ? trimmed : null;
    }
  };
  const hasCollapsedMenuMarker = (node) => {
    if (!(node instanceof Element)) return false;
    return Boolean(node.querySelector(".n-menu-item-content--collapsed"));
  };
  const nodeSelectors = [
    '[role="menuitem"]',
    '[role="treeitem"]',
    'nav a',
    'aside a',
    '[data-menu-item]',
    '[data-route-path]',
    '[data-path]',
    '.menu a',
    '.ant-menu-submenu-title',
    '.el-submenu__title',
    '.el-menu-item',
    '.tree-node',
    '.el-tree-node__content'
  ];
  const itemSelectors = '[role="menuitem"], [role="treeitem"], .ant-menu-submenu, .el-submenu, .tree-node, li';
  const parentLabelFor = (node) => {
    let current = node?.parentElement || null;
    while (current) {
      if (current.matches?.(itemSelectors)) {
        const label = toLabel(
          current.querySelector?.(
            '.ant-menu-submenu-title, .el-submenu__title, .tree-node__label, [role="menuitem"], [role="treeitem"], a, span'
          ) || current
        );
        if (label && label !== toLabel(node)) return label;
      }
      current = current.parentElement;
    }
    return null;
  };
  const inferredDepthFromIndent = (node) => {
    if (!(node instanceof Element)) return 0;
    const contentNode = node.querySelector(".n-menu-item-content") || node;
    const paddingLeft = Number.parseFloat(window.getComputedStyle(contentNode).paddingLeft || "0");
    if (!Number.isFinite(paddingLeft) || paddingLeft <= 0) return 0;
    return Math.max(0, Math.round(paddingLeft / 24) - 1);
  };
  const depthFor = (node) => {
    let depth = 0;
    let current = node?.parentElement || null;
    while (current) {
      if (current.matches?.(itemSelectors)) depth += 1;
      current = current.parentElement;
    }
    return Math.max(0, depth, inferredDepthFromIndent(node));
  };
  const siblingCounts = new Map();
  const roleMatches = (nodeRole, targetRole) => !targetRole || nodeRole === targetRole;
  const depthMatches = (depth, targetDepth) => typeof targetDepth !== "number" || depth === targetDepth;
  const parentMatches = (parentLabel, targetParent) => !targetParent || parentLabel === targetParent;
  const ariaMatches = (ariaLabel, targetAria) => !targetAria || ariaLabel === targetAria;
  const routeMatches = (routePath, targetRoutePath) => !targetRoutePath || routePath === targetRoutePath;

  for (const node of Array.from(document.querySelectorAll(nodeSelectors.join(',')))) {
    if (!isVisible(node)) continue;
    const label = toLabel(node);
    if (!label || label !== normalizeText(target?.label || "")) continue;
    const role = node.getAttribute('role') || 'menuitem';
    const ariaLabel = node.getAttribute('aria-label');
    const parentLabel = parentLabelFor(node);
    const depth = depthFor(node);
    const routePath = toRoutePath(
      node.getAttribute('href')
        || node.getAttribute('data-route-path')
        || node.getAttribute('data-path')
    );
    const siblingKey = JSON.stringify([label, parentLabel, depth, role, ariaLabel || null]);
    const siblingIndex = siblingCounts.get(siblingKey) || 0;
    siblingCounts.set(siblingKey, siblingIndex + 1);
    if (!roleMatches(role, target?.role || null)) continue;
    if (!depthMatches(depth, target?.depth)) continue;
    if (!parentMatches(parentLabel, normalizeText(target?.parent_label || ""))) continue;
    if (!ariaMatches(ariaLabel, normalizeText(target?.aria_label || ""))) continue;
    if (!routeMatches(routePath, target?.route_path || target?.page_route_path || null)) continue;
    if (typeof target?.sibling_index === 'number' && siblingIndex !== target.sibling_index) continue;
    const clickableNode = node.querySelector('.n-menu-item-content, .n-menu-item-content__arrow') || node;
    clickableNode.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
    clickableNode.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
    clickableNode.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
    if (typeof clickableNode.click === 'function') clickableNode.click();
    return { clicked: true };
  }
  return { clicked: false, reason: 'target_not_found' };
}
"""
    _MATERIALIZE_NAVIGATION_TARGETS_SCRIPT = """
async (targets) => {
  const __RUNLET_MATERIALIZE_NAVIGATION_TARGETS__ = true;
  const normalizeText = (value) => {
    if (typeof value !== "string") return "";
    return value.replace(/\\s+/g, " ").trim();
  };
  const isVisible = (node) => {
    if (!(node instanceof Element)) return false;
    const style = window.getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return style.visibility !== "hidden"
      && style.display !== "none"
      && rect.width > 0
      && rect.height > 0;
  };
  const toLabel = (node) => normalizeText(
    node?.getAttribute?.("data-menu-label")
      || node?.getAttribute?.("aria-label")
      || node?.textContent
      || ""
  );
  const toRoutePath = (value) => {
    if (typeof value !== "string") return null;
    const trimmed = value.trim();
    if (!trimmed) return null;
    try {
      return new URL(trimmed, window.location.href).pathname || null;
    } catch {
      return trimmed.startsWith("/") ? trimmed : null;
    }
  };
  const nodeSelectors = [
    '[role="menuitem"]',
    '[role="treeitem"]',
    'nav a',
    'aside a',
    '[data-menu-item]',
    '[data-route-path]',
    '[data-path]',
    '.menu a',
    '.ant-menu-submenu-title',
    '.el-submenu__title',
    '.el-menu-item',
    '.tree-node',
    '.el-tree-node__content'
  ];
  const itemSelectors = '[role="menuitem"], [role="treeitem"], .ant-menu-submenu, .el-submenu, .tree-node, li';
  const containerSelectors = '[role="menu"], nav, aside, ul, ol, [class*="menu"], [class*="nav"], [class*="tree"]';
  const parentLabelFor = (node) => {
    let current = node?.parentElement || null;
    while (current) {
      if (current.matches?.(itemSelectors)) {
        const label = toLabel(
          current.querySelector?.(
            '.ant-menu-submenu-title, .el-submenu__title, .tree-node__label, [role="menuitem"], [role="treeitem"], a, span'
          ) || current
        );
        if (label && label !== toLabel(node)) return label;
      }
      current = current.parentElement;
    }
    return null;
  };
  const depthFor = (node) => {
    let depth = 0;
    let current = node?.parentElement || null;
    while (current) {
      if (current.matches?.(itemSelectors)) depth += 1;
      current = current.parentElement;
    }
    return Math.max(0, depth);
  };
  const collectMenuNodes = (root) => {
    const scope = root || document;
    const result = [];
    const seen = new Set();
    const siblingCounts = new Map();
    const nodes = scope.querySelectorAll(nodeSelectors.join(','));
    Array.from(nodes).forEach((node, index) => {
      if (!isVisible(node)) return;
      const label = toLabel(node);
      if (!label) return;
      const href = node.getAttribute('href')
        || node.getAttribute('data-route-path')
        || node.getAttribute('data-path');
      const routePath = toRoutePath(href);
      const role = node.getAttribute('role') || 'menuitem';
      const ariaExpanded = node.getAttribute('aria-expanded');
      const className = normalizeText(node.className);
      let entryType = normalizeText(
        node.getAttribute('data-entry-type') || node.getAttribute('data-interaction-type')
      ).replace(/-/g, '_') || null;
      if (!entryType && role === 'treeitem' && ariaExpanded === 'false') {
        entryType = 'tree_expand';
      }
      if (!entryType && (
        ariaExpanded === 'false'
        || className.includes('submenu')
        || className.includes('sub-menu')
        || className.includes('subnav')
        || className.includes('n-menu-item-content--collapsed')
        || hasCollapsedMenuMarker(node)
      )) {
        entryType = 'menu_expand';
      }
      const parentLabel = parentLabelFor(node);
      const depth = depthFor(node);
      const ariaLabel = node.getAttribute('aria-label');
      const siblingKey = JSON.stringify([label, parentLabel, depth, role, ariaLabel || null]);
      const siblingIndex = siblingCounts.get(siblingKey) || 0;
      siblingCounts.set(siblingKey, siblingIndex + 1);
      const dedupeKey = JSON.stringify([label, routePath, parentLabel, depth, role, ariaLabel || null, siblingIndex]);
      if (seen.has(dedupeKey)) return;
      seen.add(dedupeKey);
      result.push({
        label,
        route_path: routePath,
        page_route_path: routePath,
        depth,
        order: index,
        role,
        aria_label: ariaLabel,
        sibling_index: siblingIndex,
        parent_label: parentLabel,
        entry_type: entryType,
        aria_expanded: ariaExpanded,
      });
    });
    const depthStack = [];
    for (const item of result) {
      if (!item.parent_label && item.depth > 0) {
        const parent = depthStack[item.depth - 1];
        if (parent && parent.label) item.parent_label = parent.label;
      }
      depthStack[item.depth] = item;
      depthStack.length = item.depth + 1;
    }
    return result;
  };
  const findTargetNode = (target) => {
    const targetLabel = normalizeText(target?.label);
    const targetParent = normalizeText(target?.parent_label);
    const targetRole = normalizeText(target?.role);
    const targetRoute = toRoutePath(target?.route_path || target?.page_route_path);
    const targetDepth = Number.isFinite(Number(target?.depth)) ? Number(target.depth) : null;
    const targetOrder = Number.isFinite(Number(target?.order)) ? Number(target.order) : null;
    const targetSiblingIndex = Number.isFinite(Number(target?.sibling_index)) ? Number(target.sibling_index) : null;
    const targetAriaLabel = normalizeText(target?.aria_label);
    const locatorCandidates = Array.isArray(target?.locator_candidates)
      ? target.locator_candidates.filter((candidate) => candidate && typeof candidate === 'object')
      : [];
    const siblingCounts = new Map();
    const toCandidateEntry = (node, index) => {
      if (!isVisible(node)) return null;
      const label = toLabel(node);
      const role = normalizeText(node.getAttribute('role') || 'menuitem');
      const parentLabel = parentLabelFor(node);
      const depth = depthFor(node);
      const ariaLabel = normalizeText(node.getAttribute('aria-label'));
      const siblingKey = JSON.stringify([label, parentLabel, depth, role, ariaLabel || null]);
      const siblingIndex = siblingCounts.get(siblingKey) || 0;
      siblingCounts.set(siblingKey, siblingIndex + 1);
      return {
        node,
        index,
        routePath: toRoutePath(
          node.getAttribute('href') || node.getAttribute('data-route-path') || node.getAttribute('data-path')
        ),
        ariaLabel,
        label,
        role,
        parentLabel,
        depth,
        siblingIndex,
      };
    };
    const indexedCandidates = Array.from(document.querySelectorAll(nodeSelectors.join(',')))
      .map((node, index) => toCandidateEntry(node, index))
      .filter((entry) => entry !== null);
    const baseMatches = indexedCandidates.filter((entry) => {
      if (!entry.label || (targetLabel && entry.label !== targetLabel)) return false;
      if (targetRole) {
        if (entry.role && entry.role !== targetRole) return false;
      }
      if (targetParent) {
        if (entry.parentLabel !== targetParent) return false;
      }
      if (targetDepth !== null && entry.depth !== targetDepth) return false;
      return true;
    });
    if (baseMatches.length === 0) return null;
    let matches = baseMatches;
    if (targetRoute) {
      const routeMatches = matches.filter((entry) => entry.routePath === targetRoute);
      if (routeMatches.length > 0) matches = routeMatches;
    }
    if (targetAriaLabel) {
      const ariaMatches = matches.filter((entry) => entry.ariaLabel === targetAriaLabel);
      if (ariaMatches.length > 0) matches = ariaMatches;
    }
    if (targetSiblingIndex !== null) {
      const siblingMatches = matches.filter((entry) => entry.siblingIndex === targetSiblingIndex);
      if (siblingMatches.length > 0) matches = siblingMatches;
    }
    for (const candidate of locatorCandidates) {
      const strategyType = normalizeText(candidate.strategy_type);
      const selector = normalizeText(candidate.selector);
      if (!strategyType || !selector) continue;
      let locatorMatches = [];
      if (strategyType === 'route_path') {
        locatorMatches = matches.filter((entry) => entry.routePath === toRoutePath(selector));
      } else if (strategyType === 'aria_label') {
        locatorMatches = matches.filter((entry) => entry.ariaLabel === selector);
      } else if (strategyType === 'sibling_index' && Number.isFinite(Number(selector))) {
        locatorMatches = matches.filter((entry) => entry.siblingIndex === Number(selector));
      } else if (strategyType === 'order' && Number.isFinite(Number(selector))) {
        locatorMatches = matches.filter((entry) => entry.index === Number(selector));
      }
      if (locatorMatches.length > 0) {
        matches = locatorMatches;
      }
    }
    if (targetOrder !== null) {
      const orderMatch = matches.find((entry) => entry.index === targetOrder);
      if (orderMatch) return orderMatch.node;
    }
    return matches[0]?.node || null;
  };
  const triggerClick = (node) => {
    if (!(node instanceof Element)) return false;
    node.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
    node.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }));
    node.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    return true;
  };
  const triggerHover = (node) => {
    if (!(node instanceof Element)) return false;
    node.dispatchEvent(new MouseEvent('pointerover', { bubbles: true, cancelable: true }));
    node.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, cancelable: true }));
    node.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true, cancelable: true }));
    return true;
  };
  const wait = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));
  const safeTargets = Array.isArray(targets) ? targets.filter((target) => target && typeof target === 'object') : [];
  const materialized = [];
  for (const target of safeTargets) {
    const node = findTargetNode(target);
    if (!node) continue;
    const targetDepth = Number.isFinite(Number(target?.depth)) ? Number(target.depth) : 0;
    const targetIdentity = {
      label: normalizeText(target?.label) || null,
      depth: targetDepth,
      role: normalizeText(target?.role) || null,
      aria_label: normalizeText(target?.aria_label) || null,
    };
    if (Number.isFinite(Number(target?.sibling_index))) {
      targetIdentity.sibling_index = Number(target.sibling_index);
    }
    const triggerNode = node.querySelector?.(
      '[aria-expanded="false"], .n-menu-item-content, .n-menu-item-content__arrow, .ant-menu-submenu-title, .el-submenu__title, .tree-node__switcher'
    ) || node;
    let applied = false;
    if (target.target_kind === 'tree_expand') {
      applied = triggerClick(triggerNode);
    } else {
      applied = triggerClick(triggerNode);
      if (!applied) {
        applied = triggerHover(node);
      } else {
        triggerHover(node);
      }
    }
    if (!applied) continue;
    await wait(150);
    const container = node.parentElement?.closest?.(containerSelectors) || node.closest?.('nav, aside, [role="menu"]') || document;
    for (const item of collectMenuNodes(container)) {
      const nextItem = { ...item };
      if (!nextItem.parent_label && nextItem.depth > targetDepth) {
        nextItem.parent_label = normalizeText(target.label) || null;
      }
      if (!nextItem.materialized_parent_identity && nextItem.depth > targetDepth) {
        nextItem.materialized_parent_identity = targetIdentity.label ? targetIdentity : null;
      }
      materialized.push(nextItem);
    }
  }
  return materialized;
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
    _STATE_PROBE_EXECUTE_ACTION_SCRIPT = """
(action) => {
  const __RUNLET_STATE_PROBE_EXECUTE__ = true;
  const normalizedAction = action && typeof action === "object" ? action : {};
  const entryType = String(normalizedAction.entry_type || normalizedAction.interaction_type || "").trim().toLowerCase();
  const stateContext = normalizedAction.state_context && typeof normalizedAction.state_context === "object"
    ? normalizedAction.state_context
    : {};

  const visible = (node) => {
    if (!(node instanceof HTMLElement)) return false;
    const style = window.getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return style.visibility !== "hidden"
      && style.display !== "none"
      && rect.width > 0
      && rect.height > 0;
  };
  const textOf = (node) =>
    String(node?.getAttribute?.("aria-label") || node?.textContent || "").trim().toLowerCase();
  const normalizeText = (value) => String(value || "").trim().toLowerCase();
  const normalizeNumber = (value) => {
    if (typeof value === "number" && Number.isFinite(value)) return String(Math.trunc(value));
    if (typeof value === "string" && /^\\d+$/.test(value.trim())) return value.trim();
    return "";
  };
  const dangerKeywords = [
    "提交", "删除", "保存", "发布", "审批", "导入", "导出", "下载",
    "submit", "delete", "remove", "save", "publish", "approve", "import", "export", "download",
  ];
  const isDangerous = (text) => dangerKeywords.some((keyword) => text.includes(keyword.toLowerCase()));
  const clickFirst = (nodes, matcher) => {
    for (const node of nodes) {
      if (!(node instanceof HTMLElement) || !visible(node)) continue;
      const text = textOf(node);
      if (isDangerous(text)) continue;
      if (!matcher(node)) continue;
      node.click();
      return true;
    }
    return false;
  };

  let applied = false;
  let reason = null;
  const tabTarget = normalizeText(stateContext.active_tab || normalizedAction.target_text || normalizedAction.label);
  const modalTarget = normalizeText(stateContext.modal_title || normalizedAction.target_text || normalizedAction.label);
  const drawerTarget = normalizeText(stateContext.drawer_title || normalizedAction.target_text || normalizedAction.label);
  const viewTarget = normalizeText(stateContext.view_mode || normalizedAction.target_text || normalizedAction.label);
  const pageNumberTarget = normalizeNumber(stateContext.page_number || stateContext.page || stateContext.page_index);

  if (entryType === "tab_switch") {
    const tabNodes = Array.from(document.querySelectorAll(
      '[role="tab"], .el-tabs__item, .ant-tabs-tab, .n-tabs-tab, [data-tab]'
    ));
    applied = clickFirst(tabNodes, (node) => {
      const text = textOf(node);
      const className = String(node.className || "").toLowerCase();
      if (node.getAttribute("role") !== "tab" && !className.includes("tab")) return false;
      if (!tabTarget) return node.getAttribute("aria-selected") !== "true";
      return text.includes(tabTarget);
    });
  } else if (entryType === "open_modal" || entryType === "open_drawer") {
    const target = entryType === "open_drawer" ? drawerTarget : modalTarget;
    const triggerNodes = Array.from(document.querySelectorAll(
      'button, [role="button"], [aria-haspopup="dialog"], [data-action], .ant-btn, .el-button'
    ));
    const defaultKeywords = ["新增", "新建", "创建", "添加", "open", "new", "create", "add", "drawer", "modal"];
    applied = clickFirst(triggerNodes, (node) => {
      const text = textOf(node);
      const actionHint = normalizeText(node.getAttribute("data-action") || node.getAttribute("data-testid"));
      const hasDialogSemantics = node.getAttribute("aria-haspopup") === "dialog";
      const hasCreateHint = defaultKeywords.some((keyword) => text.includes(keyword.toLowerCase()))
        || defaultKeywords.some((keyword) => actionHint.includes(keyword.toLowerCase()))
        || hasDialogSemantics;
      if (!hasCreateHint) return false;
      if (target) return text.includes(target) || actionHint.includes(target);
      return true;
    });
  } else if (entryType === "toggle_view") {
    const nodes = Array.from(document.querySelectorAll(
      'button, [role="button"], [data-view-mode], .ant-segmented-item, .el-radio-button'
    ));
    applied = clickFirst(nodes, (node) => {
      const text = textOf(node);
      if (viewTarget) return text.includes(viewTarget);
      return text.includes("列表") || text.includes("表格") || text.includes("卡片")
        || text.includes("list") || text.includes("table") || text.includes("grid") || text.includes("card");
    });
  } else if (entryType === "paginate_probe") {
    const nodes = Array.from(document.querySelectorAll(
      '[role="button"], button, a, li, .ant-pagination-item, .el-pager li, .pagination *'
    ));
    applied = clickFirst(nodes, (node) => {
      const text = textOf(node);
      const inPager = !!node.closest(
        '.pagination, .ant-pagination, .el-pagination, .el-pager, [aria-label*="pagination"], [class*="pager"]'
      );
      if (!inPager && !/^\\d+$/.test(text)) return false;
      if (pageNumberTarget) return text === pageNumberTarget || text.includes(`page ${pageNumberTarget}`);
      return text.includes("下一页") || text.includes("next");
    });
  } else if (entryType === "expand_panel" || entryType === "tree_expand") {
    const nodes = Array.from(document.querySelectorAll(
      '[aria-expanded="false"], [role="button"], .el-collapse-item__header, .ant-collapse-header, .tree-node'
    ));
    applied = clickFirst(nodes, (node) => {
      const ariaExpanded = node.getAttribute("aria-expanded");
      if (ariaExpanded === "false") return true;
      const text = textOf(node);
      return text.includes("展开") || text.includes("expand") || text.includes("更多");
    });
  } else {
    reason = "unsupported_action";
  }

  if (!applied && reason === null) {
    reason = "action_not_applied";
  }
  return {
    applied,
    reason,
    entry_type: entryType,
  };
}
"""
    _STATE_PROBE_MODAL_KEYWORDS = ("新增", "新建", "创建", "添加", "add", "new", "create")
    _STATE_PROBE_VIEW_KEYWORDS = ("列表", "卡片", "视图", "table", "grid", "list", "card")

    async def open_context(
        self,
        *,
        base_url: str,
        storage_state: dict[str, object],
        entry_url: str | None = None,
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
        initial_entry_url = entry_url or base_url
        await page.goto(initial_entry_url, wait_until="domcontentloaded")  # pragma: no cover

        class _Session:
            framework_hint = None
            _settled = False
            _last_ready_location: str | None = None
            _entry_url = initial_entry_url
            _cached_full_route_hints: list[dict[str, object]] | None = None
            _cached_full_materialized_menu_nodes: list[dict[str, object]] | None = None

            async def _ensure_settled(self_nonlocal) -> None:
                current_location = self_nonlocal._current_page_location()
                if (
                    self_nonlocal._settled
                    and current_location is not None
                    and current_location == self_nonlocal._last_ready_location
                ):
                    return
                initial_wait_ms = (
                    PlaywrightBrowserFactory._INITIAL_SETTLE_MS
                    if not self_nonlocal._settled
                    else PlaywrightBrowserFactory._ROUTE_SETTLE_MS
                )
                await page.wait_for_timeout(initial_wait_ms)
                samples: list[dict[str, object]] = []
                for sample_index in range(PlaywrightBrowserFactory._APP_READINESS_MAX_SAMPLES):
                    samples.append(await self_nonlocal._collect_readiness_sample())
                    readiness = evaluate_app_readiness(
                        samples=samples,
                        stabilization_window=PlaywrightBrowserFactory._APP_READINESS_WINDOW,
                    )
                    if readiness.shell_ready and readiness.route_ready and readiness.content_ready:
                        break
                    if sample_index < PlaywrightBrowserFactory._APP_READINESS_MAX_SAMPLES - 1:
                        await page.wait_for_timeout(PlaywrightBrowserFactory._ROUTE_SETTLE_MS)
                self_nonlocal._settled = True
                self_nonlocal._last_ready_location = self_nonlocal._current_page_location() or current_location

            async def collect_route_hints(
                self_nonlocal,
                *,
                crawl_scope: str,
            ) -> list[dict[str, object]]:
                if crawl_scope == "full" and self_nonlocal._cached_full_route_hints is not None:
                    return self_nonlocal._clone_dict_list(self_nonlocal._cached_full_route_hints)
                await self_nonlocal._ensure_settled()
                collected = await page.evaluate(PlaywrightBrowserFactory._ROUTE_HINTS_SCRIPT)
                route_hints = self_nonlocal._ensure_dict_list(collected)
                if crawl_scope != "full":
                    return route_hints
                discovered_by_click = await self_nonlocal._discover_route_hints_by_clicking_menu_leaves()
                merged_route_hints = self_nonlocal._merge_route_hints(route_hints, discovered_by_click)
                self_nonlocal._cached_full_route_hints = self_nonlocal._clone_dict_list(merged_route_hints)
                return self_nonlocal._clone_dict_list(merged_route_hints)

            async def collect_route_snapshot(
                self_nonlocal,
                *,
                crawl_scope: str,
            ) -> dict[str, object]:
                del crawl_scope
                await self_nonlocal._ensure_settled()
                return await self_nonlocal._collect_route_snapshot_raw()

            async def _collect_route_snapshot_raw(self_nonlocal) -> dict[str, object]:
                runtime_snapshot_raw = await self_nonlocal._evaluate_with_optional_arg(
                    PlaywrightBrowserFactory._ROUTE_RUNTIME_SNAPSHOT_SCRIPT,
                    {},
                )
                runtime_snapshot = runtime_snapshot_raw if isinstance(runtime_snapshot_raw, dict) else {}
                current_url = self_nonlocal._clean_text(
                    getattr(page, "url", None) or getattr(page, "current_url", None)
                )
                fallback_pathname, fallback_hash = self_nonlocal._parse_current_location(current_url)

                route_snapshot = resolve_route_snapshot(
                    pathname=runtime_snapshot.get("pathname") or fallback_pathname,
                    location_hash=runtime_snapshot.get("location_hash") or fallback_hash,
                    router_route=runtime_snapshot.get("router_route"),
                    history_route=runtime_snapshot.get("history_route"),
                )
                return {
                    "resolved_route": route_snapshot.resolved_route,
                    "route_source": route_snapshot.route_source,
                    "pathname": route_snapshot.pathname,
                    "hash_route": route_snapshot.hash_route,
                    "router_route": route_snapshot.router_route,
                    "history_route": route_snapshot.history_route,
                }

            async def collect_dom_menu_skeleton(
                self_nonlocal,
                *,
                crawl_scope: str,
            ) -> list[dict[str, object]]:
                del crawl_scope
                await self_nonlocal._ensure_settled()
                collected = await page.evaluate(PlaywrightBrowserFactory._MENU_NODES_SCRIPT)
                return self_nonlocal._ensure_dict_list(collected)

            async def materialize_navigation_targets(
                self_nonlocal,
                *,
                targets: list[dict[str, object]],
                crawl_scope: str,
            ) -> list[dict[str, object]]:
                del crawl_scope
                await self_nonlocal._ensure_settled()
                if not targets:
                    return []
                collected = await self_nonlocal._evaluate_with_optional_arg(
                    PlaywrightBrowserFactory._MATERIALIZE_NAVIGATION_TARGETS_SCRIPT,
                    targets,
                )
                materialized = self_nonlocal._ensure_dict_list(collected)
                if materialized:
                    return materialized
                return await self_nonlocal._materialize_navigation_targets_via_locator(targets)

            async def collect_dom_menu_nodes(
                self_nonlocal,
                *,
                crawl_scope: str,
            ) -> list[dict[str, object]]:
                return await self_nonlocal._collect_materialized_menu_nodes(crawl_scope=crawl_scope)

            async def collect_dom_elements(
                self_nonlocal,
                *,
                crawl_scope: str,
            ) -> list[dict[str, object]]:
                await self_nonlocal._ensure_settled()
                menu_nodes = await self_nonlocal._collect_materialized_menu_nodes(crawl_scope=crawl_scope)
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
                    route_hints = await self_nonlocal.collect_route_hints(crawl_scope="full")
                    for hint in route_hints:
                        if isinstance(hint, dict):
                            add_route(hint.get("path") or hint.get("route_path"))
                    for node in menu_nodes:
                        if isinstance(node, dict):
                            add_route(node.get("route_path") or node.get("page_route_path"))
                else:
                    add_route(await self_nonlocal._resolve_current_route_path())

                if not route_paths:
                    add_route(await self_nonlocal._resolve_current_route_path())

                elements: list[dict[str, object]] = []
                seen_payloads: set[str] = set()
                for route_path in route_paths:
                    await page.goto(
                        self_nonlocal._build_route_visit_url(route_path),
                        wait_until="domcontentloaded",
                    )
                    await self_nonlocal._stabilize_after_navigation()
                    resolved_route = await self_nonlocal._resolve_current_route_path(default_route=route_path)
                    collected = await self_nonlocal._collect_current_page_elements(default_route=resolved_route)
                    for payload in collected:
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

            async def visit_page_target(
                self_nonlocal,
                *,
                page_target: dict[str, object],
                crawl_scope: str,
            ) -> dict[str, object]:
                del crawl_scope
                await self_nonlocal._ensure_settled()
                route_path = self_nonlocal._normalize_path(
                    page_target.get("route_hint") or page_target.get("route_path")
                )
                warning_messages: list[str] = []
                if route_path is None:
                    warning_messages.append("route_unresolved")
                    return {
                        "route_path": "/",
                        "resolved_route": "/",
                        "state_context": {"active_tab": "default"},
                        "elements": [],
                        "warning_messages": warning_messages,
                    }

                await page.goto(
                    self_nonlocal._build_route_visit_url(route_path),
                    wait_until="domcontentloaded",
                )
                await self_nonlocal._stabilize_after_navigation()

                route_snapshot = await self_nonlocal._collect_route_snapshot_raw()
                resolved_route = self_nonlocal._normalize_path(route_snapshot.get("resolved_route")) or route_path
                if resolved_route != route_path:
                    warning_messages.append("route_unresolved")

                elements = await self_nonlocal._collect_current_page_elements(default_route=resolved_route)
                metadata = await self_nonlocal.collect_page_metadata(crawl_scope="current")
                if any(
                    isinstance(item, dict)
                    and (
                        item.get("reachable") is False
                        or (isinstance(item.get("status_code"), int) and item.get("status_code") >= 400)
                    )
                    for item in metadata
                ):
                    warning_messages.append("route_visible_but_unreachable")

                return {
                    "route_path": route_path,
                    "resolved_route": resolved_route,
                    "state_context": {"active_tab": "default"},
                    "elements": elements,
                    "page_metadata": metadata,
                    "warning_messages": warning_messages,
                }

            async def collect_state_probe_baseline(
                self_nonlocal,
                *,
                crawl_scope: str,
            ) -> list[dict[str, object]]:
                collected_elements = await self_nonlocal.collect_dom_elements(crawl_scope=crawl_scope)
                route_elements: dict[str, list[dict[str, object]]] = {}
                for item in collected_elements:
                    if not isinstance(item, dict):
                        continue
                    route_path = self_nonlocal._normalize_path(item.get("page_route_path") or item.get("route_path"))
                    if route_path is None:
                        continue
                    route_elements.setdefault(route_path, []).append(dict(item))

                baseline_states: list[dict[str, object]] = []
                for route_path in sorted(route_elements):
                    baseline_states.append(
                        {
                            "route_path": route_path,
                            "state_context": {"active_tab": "default"},
                            "elements": route_elements[route_path],
                        }
                    )
                return baseline_states

            async def collect_state_probe_actions(
                self_nonlocal,
                *,
                crawl_scope: str,
            ) -> list[dict[str, object]]:
                await self_nonlocal._ensure_settled()
                dom_elements = await self_nonlocal.collect_dom_elements(crawl_scope=crawl_scope)
                normalized_dom_elements = [item for item in dom_elements if isinstance(item, dict)]

                action_candidates: list[dict[str, object]] = []
                seen_actions: set[str] = set()
                discovered_routes: set[str] = set()
                route_action_counts: dict[str, int] = {}

                for element in normalized_dom_elements:
                    route_path = self_nonlocal._normalize_path(element.get("page_route_path") or element.get("route_path"))
                    if route_path is None:
                        continue
                    discovered_routes.add(route_path)
                    role = self_nonlocal._clean_text(element.get("role"))
                    element_type = self_nonlocal._clean_text(element.get("element_type"))
                    text = self_nonlocal._clean_text(element.get("text") or element.get("element_text")) or ""
                    lower_text = text.lower()
                    if role == "tab" and text:
                        action = {
                            "route_path": route_path,
                            "entry_type": "tab_switch",
                            "state_context": {"active_tab": lower_text},
                        }
                        self_nonlocal._append_unique_action(
                            action_candidates=action_candidates,
                            seen_actions=seen_actions,
                            action=action,
                        )
                        route_action_counts[route_path] = route_action_counts.get(route_path, 0) + 1
                    if element_type == "button" and any(
                        keyword in lower_text for keyword in PlaywrightBrowserFactory._STATE_PROBE_MODAL_KEYWORDS
                    ):
                        action = {
                            "route_path": route_path,
                            "entry_type": "open_modal",
                            "state_context": {"modal_title": lower_text or "open_modal"},
                        }
                        self_nonlocal._append_unique_action(
                            action_candidates=action_candidates,
                            seen_actions=seen_actions,
                            action=action,
                        )
                        route_action_counts[route_path] = route_action_counts.get(route_path, 0) + 1
                    if text.isdigit():
                        action = {
                            "route_path": route_path,
                            "entry_type": "paginate_probe",
                            "state_context": {"page_number": int(text)},
                        }
                        self_nonlocal._append_unique_action(
                            action_candidates=action_candidates,
                            seen_actions=seen_actions,
                            action=action,
                        )
                        route_action_counts[route_path] = route_action_counts.get(route_path, 0) + 1
                    if element_type == "button" and any(
                        keyword in lower_text for keyword in PlaywrightBrowserFactory._STATE_PROBE_VIEW_KEYWORDS
                    ):
                        action = {
                            "route_path": route_path,
                            "entry_type": "toggle_view",
                            "state_context": {"view_mode": lower_text},
                        }
                        self_nonlocal._append_unique_action(
                            action_candidates=action_candidates,
                            seen_actions=seen_actions,
                            action=action,
                        )
                        route_action_counts[route_path] = route_action_counts.get(route_path, 0) + 1

                if not discovered_routes:
                    route_hints = await self_nonlocal.collect_route_hints(crawl_scope="current")
                    for hint in route_hints:
                        if not isinstance(hint, dict):
                            continue
                        normalized_route = self_nonlocal._normalize_path(hint.get("path") or hint.get("route_path"))
                        if normalized_route is not None:
                            discovered_routes.add(normalized_route)

                for route_path in sorted(discovered_routes):
                    if route_action_counts.get(route_path, 0) == 0:
                        self_nonlocal._append_unique_action(
                            action_candidates=action_candidates,
                            seen_actions=seen_actions,
                            action={
                                "route_path": route_path,
                                "entry_type": "tab_switch",
                                "state_context": {"active_tab": "default"},
                            },
                        )
                        route_action_counts[route_path] = 1
                return action_candidates

            async def perform_state_probe_action(
                self_nonlocal,
                *,
                action: dict[str, object],
                crawl_scope: str,
            ) -> dict[str, object]:
                del crawl_scope
                await self_nonlocal._ensure_settled()
                action = build_navigation_action_payload(
                    target=action,
                    route_path=action.get("route_path") or action.get("page_route_path") or action.get("route_hint"),
                    base_state_context=action.get("state_context"),
                )
                entry_type = self_nonlocal._clean_text(action.get("entry_type") or action.get("interaction_type"))
                if entry_type is None or entry_type.lower().replace("-", "_") not in ALLOWED_STATE_PROBE_ACTIONS:
                    raise ValueError("unsafe state probe action")

                route_path = self_nonlocal._normalize_path(action.get("route_path") or action.get("page_route_path"))
                if route_path is not None:
                    await page.goto(
                        self_nonlocal._build_route_visit_url(route_path),
                        wait_until="domcontentloaded",
                    )
                    await self_nonlocal._stabilize_after_navigation()
                else:
                    route_hints = await self_nonlocal.collect_route_hints(crawl_scope="current")
                    route_path = "/"
                    for hint in route_hints:
                        if not isinstance(hint, dict):
                            continue
                        normalized_path = self_nonlocal._normalize_path(hint.get("path") or hint.get("route_path"))
                        if normalized_path is not None:
                            route_path = normalized_path
                            break

                execution_result = await self_nonlocal._evaluate_with_optional_arg(
                    PlaywrightBrowserFactory._STATE_PROBE_EXECUTE_ACTION_SCRIPT,
                    action,
                )
                applied = isinstance(execution_result, dict) and execution_result.get("applied") is True
                execution_reason = (
                    execution_result.get("reason")
                    if isinstance(execution_result, dict) and isinstance(execution_result.get("reason"), str)
                    else None
                )
                if applied:
                    await self_nonlocal._wait_for_route_render()
                    await page.wait_for_timeout(PlaywrightBrowserFactory._ROUTE_SETTLE_MS)
                    collected = await page.evaluate(PlaywrightBrowserFactory._DOM_ELEMENTS_SCRIPT)
                    elements = (
                        [item for item in collected if isinstance(item, dict)]
                        if isinstance(collected, list)
                        else []
                    )
                else:
                    elements = []
                state_context = action.get("state_context")
                if not isinstance(state_context, dict):
                    state_context = {}
                return {
                    "route_path": route_path,
                    "state_context": state_context,
                    "elements": elements,
                    "probe_applied": applied,
                    "probe_apply_reason": execution_reason,
                }

            async def perform_navigation_target(
                self_nonlocal,
                *,
                target: dict[str, object],
                page_context: dict[str, object],
                crawl_scope: str,
            ) -> dict[str, object]:
                del crawl_scope
                await self_nonlocal._ensure_settled()
                action = build_navigation_action_payload(
                    target=target,
                    route_path=target.get("route_hint") or target.get("route_path"),
                    base_state_context=target.get("state_context"),
                )
                route_path = self_nonlocal._normalize_path(action.get("route_path") or action.get("route_hint"))
                current_route = self_nonlocal._normalize_path(
                    page_context.get("resolved_route") or page_context.get("route_path")
                )

                if route_path is not None and route_path != current_route:
                    await page.goto(
                        self_nonlocal._build_route_visit_url(route_path),
                        wait_until="domcontentloaded",
                    )
                    await self_nonlocal._stabilize_after_navigation()
                    route_snapshot = await self_nonlocal._collect_route_snapshot_raw()
                    current_route = self_nonlocal._normalize_path(route_snapshot.get("resolved_route")) or route_path
                    if current_route != route_path:
                        state_context = target.get("state_context")
                        if not isinstance(state_context, dict):
                            state_context = {}
                        return {
                            "route_path": route_path,
                            "state_context": state_context,
                            "elements": [],
                            "probe_applied": False,
                            "probe_apply_reason": "route_unresolved",
                        }
                return await self_nonlocal.perform_state_probe_action(
                    action=action,
                    crawl_scope="current",
                )

            async def _evaluate_with_optional_arg(
                self_nonlocal,
                script: str,
                arg: object,
            ):
                try:
                    return await page.evaluate(script, arg)
                except TypeError:
                    try:
                        return await page.evaluate(script)
                    except Exception:
                        return {"applied": False, "reason": "action_execution_not_supported"}
                except Exception:
                    return {"applied": False, "reason": "action_execution_not_supported"}

            async def _collect_current_page_elements(
                self_nonlocal,
                *,
                default_route: str,
            ) -> list[dict[str, object]]:
                collected = await page.evaluate(PlaywrightBrowserFactory._DOM_ELEMENTS_SCRIPT)
                if not isinstance(collected, list):
                    return []
                route_snapshot = await self_nonlocal._collect_route_snapshot_raw()
                current_pathname = self_nonlocal._normalize_path(route_snapshot.get("pathname"))
                current_hash_route = self_nonlocal._normalize_path(route_snapshot.get("hash_route"))
                elements: list[dict[str, object]] = []
                for item in collected:
                    if not isinstance(item, dict):
                        continue
                    payload = dict(item)
                    normalized_route = self_nonlocal._normalize_path(
                        payload.get("page_route_path") or payload.get("route_path")
                    )
                    if (
                        normalized_route is None
                        or (normalized_route == "/" and default_route != "/")
                        or (
                            current_hash_route is not None
                            and current_pathname is not None
                            and normalized_route == current_pathname
                            and default_route != current_pathname
                        )
                    ):
                        payload["page_route_path"] = default_route
                    elements.append(payload)
                return elements

            async def _collect_materialized_menu_nodes(
                self_nonlocal,
                *,
                crawl_scope: str,
            ) -> list[dict[str, object]]:
                if (
                    crawl_scope == "full"
                    and self_nonlocal._cached_full_materialized_menu_nodes is not None
                ):
                    return self_nonlocal._clone_dict_list(
                        self_nonlocal._cached_full_materialized_menu_nodes
                    )
                skeleton = await self_nonlocal.collect_dom_menu_skeleton(crawl_scope=crawl_scope)
                materialized = await self_nonlocal.materialize_navigation_targets(
                    targets=build_menu_expand_targets(skeleton),
                    crawl_scope=crawl_scope,
                )
                merged_menu_nodes = merge_menu_skeleton_and_materialized_nodes(
                    skeleton=skeleton,
                    materialized=materialized,
                )
                if crawl_scope == "full":
                    self_nonlocal._cached_full_materialized_menu_nodes = self_nonlocal._clone_dict_list(
                        merged_menu_nodes
                    )
                return self_nonlocal._clone_dict_list(merged_menu_nodes)

            async def _discover_route_hints_by_clicking_menu_leaves(
                self_nonlocal,
            ) -> list[dict[str, object]]:
                menu_nodes = await self_nonlocal._collect_materialized_menu_nodes(crawl_scope="full")
                discovered: list[dict[str, object]] = []
                seen_routes: set[str] = set()
                at_entry_location = True

                for item in sorted(
                    menu_nodes,
                    key=lambda candidate: (
                        self_nonlocal._to_sort_int(candidate.get("depth")),
                        self_nonlocal._to_sort_int(candidate.get("order") or candidate.get("sort_order")),
                    ),
                ):
                    if not self_nonlocal._is_route_less_leaf_menu_node(item):
                        continue
                    if not at_entry_location:
                        await self_nonlocal._goto_entry_location()
                        at_entry_location = True
                    await self_nonlocal._expand_navigation_ancestors(
                        item=item,
                        menu_nodes=menu_nodes,
                    )
                    before_route = await self_nonlocal._resolve_current_route_path()
                    clicked = await self_nonlocal._click_navigation_target(item)
                    if not clicked:
                        continue
                    await self_nonlocal._wait_for_route_change(previous_route=before_route)
                    await self_nonlocal._stabilize_after_navigation()
                    route_snapshot = await self_nonlocal._collect_route_snapshot_raw()
                    resolved_route = self_nonlocal._normalize_path(route_snapshot.get("resolved_route"))
                    if resolved_route is None or resolved_route == before_route:
                        clicked = await self_nonlocal._click_navigation_target_via_locator(item)
                        if not clicked:
                            continue
                        await self_nonlocal._wait_for_route_change(previous_route=before_route)
                        await self_nonlocal._stabilize_after_navigation()
                        route_snapshot = await self_nonlocal._collect_route_snapshot_raw()
                        resolved_route = self_nonlocal._normalize_path(route_snapshot.get("resolved_route"))
                    if resolved_route is None or resolved_route in seen_routes:
                        continue
                    page_title = self_nonlocal._clean_text(
                        await self_nonlocal._evaluate_with_optional_arg("() => document.title", {})
                    )
                    seen_routes.add(resolved_route)
                    discovered.append({"path": resolved_route, "title": page_title})
                    at_entry_location = False
                if discovered and not at_entry_location:
                    await self_nonlocal._goto_entry_location()
                return discovered

            def _ensure_dict_list(self_nonlocal, value: object) -> list[dict[str, object]]:
                if not isinstance(value, list):
                    return []
                result: list[dict[str, object]] = []
                for item in value:
                    if isinstance(item, dict):
                        result.append(item)
                return result

            def _clone_dict_list(self_nonlocal, value: list[dict[str, object]]) -> list[dict[str, object]]:
                return [dict(item) for item in value]

            async def _materialize_navigation_targets_via_locator(
                self_nonlocal,
                targets: list[dict[str, object]],
            ) -> list[dict[str, object]]:
                materialized: list[dict[str, object]] = []
                for target in targets:
                    if not isinstance(target, dict):
                        continue
                    clicked = await self_nonlocal._click_navigation_target_via_locator(target)
                    if not clicked:
                        continue
                    await page.wait_for_timeout(300)
                    collected = self_nonlocal._ensure_dict_list(
                        await self_nonlocal._evaluate_with_optional_arg(
                            PlaywrightBrowserFactory._MENU_NODES_SCRIPT,
                            {},
                        )
                    )
                    target_depth = self_nonlocal._to_sort_int(target.get("depth"))
                    target_label = self_nonlocal._clean_text(target.get("label"))
                    for item in collected:
                        next_item = dict(item)
                        if (
                            target_label is not None
                            and self_nonlocal._to_sort_int(next_item.get("depth")) > target_depth
                            and next_item.get("parent_label") is None
                        ):
                            next_item["parent_label"] = target_label
                        materialized.append(next_item)
                return materialized

            async def _expand_navigation_ancestors(
                self_nonlocal,
                *,
                item: dict[str, object],
                menu_nodes: list[dict[str, object]],
            ) -> None:
                ancestors: list[dict[str, object]] = []
                current = item
                seen_keys: set[str] = set()
                while True:
                    parent = self_nonlocal._find_parent_menu_node(item=current, menu_nodes=menu_nodes)
                    if parent is None:
                        break
                    parent_key = self_nonlocal._menu_node_key(parent)
                    if parent_key in seen_keys:
                        break
                    seen_keys.add(parent_key)
                    if self_nonlocal._is_expand_menu_node(parent):
                        ancestors.append(parent)
                    current = parent
                for ancestor in reversed(ancestors):
                    clicked = await self_nonlocal._click_navigation_target_via_locator(ancestor)
                    if not clicked:
                        clicked = await self_nonlocal._click_navigation_target(ancestor)
                    if clicked:
                        await page.wait_for_timeout(300)

            def _find_parent_menu_node(
                self_nonlocal,
                *,
                item: dict[str, object],
                menu_nodes: list[dict[str, object]],
            ) -> dict[str, object] | None:
                parent_label = self_nonlocal._clean_text(item.get("parent_label"))
                if parent_label is None:
                    return None
                parent_depth = max(0, self_nonlocal._to_sort_int(item.get("depth")) - 1)
                parent_identity = (
                    item.get("parent_navigation_identity")
                    if isinstance(item.get("parent_navigation_identity"), dict)
                    else None
                )
                candidates: list[dict[str, object]] = []
                for candidate in menu_nodes:
                    if not isinstance(candidate, dict):
                        continue
                    if self_nonlocal._clean_text(candidate.get("label")) != parent_label:
                        continue
                    if self_nonlocal._to_sort_int(candidate.get("depth")) != parent_depth:
                        continue
                    candidates.append(candidate)
                if not candidates:
                    return None
                if parent_identity is not None:
                    for candidate in candidates:
                        if self_nonlocal._matches_navigation_identity(
                            candidate=candidate,
                            navigation_identity=parent_identity,
                        ):
                            return candidate
                expand_candidates = [
                    candidate for candidate in candidates if self_nonlocal._is_expand_menu_node(candidate)
                ]
                if len(expand_candidates) == 1:
                    return expand_candidates[0]
                if len(candidates) == 1:
                    return candidates[0]
                return expand_candidates[0] if expand_candidates else candidates[0]

            def _matches_navigation_identity(
                self_nonlocal,
                *,
                candidate: dict[str, object],
                navigation_identity: dict[str, object],
            ) -> bool:
                return (
                    self_nonlocal._clean_text(candidate.get("label"))
                    == self_nonlocal._clean_text(navigation_identity.get("label"))
                    and self_nonlocal._to_sort_int(candidate.get("depth"))
                    == self_nonlocal._to_sort_int(navigation_identity.get("depth"))
                    and (
                        self_nonlocal._clean_text(candidate.get("role")) or "menuitem"
                    )
                    == (self_nonlocal._clean_text(navigation_identity.get("role")) or "menuitem")
                    and self_nonlocal._to_optional_int(candidate.get("sibling_index"))
                    == self_nonlocal._to_optional_int(navigation_identity.get("sibling_index"))
                )

            async def _collect_readiness_sample(self_nonlocal) -> dict[str, object]:
                route_snapshot = await self_nonlocal._collect_route_snapshot_raw()
                shell_ready_raw = await self_nonlocal._evaluate_with_optional_arg(
                    """
() => {
  const readyState = document.readyState;
  const hasShell = Boolean(
    document.querySelector("#app, #root, main, [role='main'], [data-app-root]")
      || document.body?.children?.length
  );
  return {
    shell_ready: (readyState === "interactive" || readyState === "complete") && hasShell,
  };
}
""",
                    {},
                )
                shell_ready = (
                    isinstance(shell_ready_raw, dict) and shell_ready_raw.get("shell_ready") is True
                )
                try:
                    content_ready = bool(await page.evaluate(PlaywrightBrowserFactory._ROUTE_RENDER_READY_SCRIPT))
                except Exception:
                    content_ready = False
                return {
                    "resolved_route": route_snapshot.get("resolved_route"),
                    "shell_ready": shell_ready,
                    "content_ready": content_ready,
                }

            async def _wait_for_route_change(
                self_nonlocal,
                *,
                previous_route: str | None,
            ) -> str | None:
                normalized_previous = self_nonlocal._normalize_path(previous_route)
                if normalized_previous is None:
                    return None
                for _ in range(12):
                    route_snapshot = await self_nonlocal._collect_route_snapshot_raw()
                    resolved_route = self_nonlocal._normalize_path(route_snapshot.get("resolved_route"))
                    if resolved_route is not None and resolved_route != normalized_previous:
                        return resolved_route
                    await page.wait_for_timeout(250)
                return normalized_previous

            def _append_unique_action(
                self_nonlocal,
                *,
                action_candidates: list[dict[str, object]],
                seen_actions: set[str],
                action: dict[str, object],
            ) -> None:
                serialized = json.dumps(action, ensure_ascii=False, sort_keys=True)
                if serialized in seen_actions:
                    return
                seen_actions.add(serialized)
                action_candidates.append(action)

            def _normalize_path(self_nonlocal, value: object) -> str | None:
                if not isinstance(value, str):
                    return None
                normalized = value.strip()
                if not normalized or not normalized.startswith("/"):
                    return None
                return normalized.rstrip("/") or "/"

            def _merge_route_hints(
                self_nonlocal,
                primary: list[dict[str, object]],
                secondary: list[dict[str, object]],
            ) -> list[dict[str, object]]:
                merged: list[dict[str, object]] = []
                index_by_path: dict[str, int] = {}
                for collection in (primary, secondary):
                    for item in collection:
                        if not isinstance(item, dict):
                            continue
                        route_path = self_nonlocal._normalize_path(item.get("path") or item.get("route_path"))
                        if route_path is None:
                            continue
                        normalized = dict(item)
                        normalized["path"] = route_path
                        existing_index = index_by_path.get(route_path)
                        if existing_index is None:
                            index_by_path[route_path] = len(merged)
                            merged.append(normalized)
                            continue
                        existing = merged[existing_index]
                        if existing.get("title") in {None, ""} and normalized.get("title") not in {None, ""}:
                            existing["title"] = normalized.get("title")
                return merged

            async def _click_navigation_target(self_nonlocal, target: dict[str, object]) -> bool:
                clicked = await self_nonlocal._evaluate_with_optional_arg(
                    PlaywrightBrowserFactory._CLICK_NAVIGATION_TARGET_SCRIPT,
                    target,
                )
                if isinstance(clicked, dict) and clicked.get("clicked") is True:
                    return True
                return await self_nonlocal._click_navigation_target_via_locator(target)

            async def _click_navigation_target_via_locator(
                self_nonlocal,
                target: dict[str, object],
            ) -> bool:
                label = self_nonlocal._clean_text(target.get("label"))
                if label is None:
                    return False
                get_by_role = getattr(page, "get_by_role", None)
                if not callable(get_by_role):
                    return False
                role = self_nonlocal._clean_text(target.get("role")) or "menuitem"
                sibling_index = self_nonlocal._to_optional_int(target.get("sibling_index")) or 0
                try:
                    locator = get_by_role(role, name=label, exact=True)
                except TypeError:
                    try:
                        locator = get_by_role(role, name=label)
                    except Exception:
                        locator = None
                except Exception:
                    locator = None
                if locator is None:
                    return False
                target_locator = locator.nth(sibling_index)
                try:
                    if await target_locator.count() == 0:
                        return False
                except Exception:
                    pass
                inner_locator_factory = getattr(target_locator, "locator", None)
                if callable(inner_locator_factory):
                    try:
                        inner_locator = inner_locator_factory(".n-menu-item-content, .n-menu-item-content__arrow").first
                        inner_count = await inner_locator.count()
                        if inner_count > 0:
                            target_locator = inner_locator
                    except Exception:
                        pass
                try:
                    await target_locator.click(timeout=750)
                    return True
                except Exception:
                    dispatch_event = getattr(target_locator, "dispatch_event", None)
                    if callable(dispatch_event):
                        try:
                            await dispatch_event("click")
                            return True
                        except Exception:
                            return False
                return False

            def _clean_text(self_nonlocal, value: object) -> str | None:
                if not isinstance(value, str):
                    return None
                cleaned = value.strip()
                return cleaned or None

            def _build_route_visit_url(self_nonlocal, route_path: str) -> str:
                normalized_route = self_nonlocal._normalize_path(route_path) or "/"
                parsed_entry = urlparse(self_nonlocal._entry_url)
                entry_hash_route = self_nonlocal._normalize_path(parsed_entry.fragment)
                entry_path = parsed_entry.path or "/"
                if (
                    entry_hash_route is not None
                    and normalized_route != entry_path
                    and not normalized_route.startswith(f"{entry_path.rstrip('/')}/")
                ):
                    return urlunparse(
                        (
                            parsed_entry.scheme,
                            parsed_entry.netloc,
                            entry_path,
                            "",
                            "",
                            normalized_route,
                        )
                    )
                return f"{base_url.rstrip('/')}{normalized_route}"

            def _parse_current_location(self_nonlocal, current_url: str | None) -> tuple[str | None, str | None]:
                if current_url is None:
                    return None, None
                try:
                    parsed = urlparse(current_url)
                except Exception:
                    return None, None
                pathname = parsed.path or "/"
                location_hash = parsed.fragment
                normalized_hash = f"#{location_hash}" if location_hash else None
                return pathname, normalized_hash

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

            def _current_page_location(self_nonlocal) -> str | None:
                return self_nonlocal._clean_text(getattr(page, "url", None) or getattr(page, "current_url", None))

            async def _resolve_current_route_path(self_nonlocal, default_route: str = "/") -> str:
                route_snapshot = await self_nonlocal._collect_route_snapshot_raw()
                return self_nonlocal._normalize_path(route_snapshot.get("resolved_route")) or default_route

            async def _goto_entry_location(self_nonlocal) -> None:
                await page.goto(self_nonlocal._entry_url, wait_until="domcontentloaded")
                await self_nonlocal._stabilize_after_navigation()

            async def _stabilize_after_navigation(self_nonlocal) -> None:
                await self_nonlocal._wait_for_route_render()
                await self_nonlocal._ensure_settled()

            def _menu_node_key(self_nonlocal, item: dict[str, object]) -> str:
                normalized = {
                    "label": self_nonlocal._clean_text(item.get("label")),
                    "parent_label": self_nonlocal._clean_text(item.get("parent_label")),
                    "depth": self_nonlocal._to_sort_int(item.get("depth")),
                    "role": self_nonlocal._clean_text(item.get("role")),
                    "aria_label": self_nonlocal._clean_text(item.get("aria_label")),
                    "sibling_index": self_nonlocal._to_optional_int(item.get("sibling_index")),
                }
                return json.dumps(normalized, ensure_ascii=False, sort_keys=True)

            def _menu_parent_key(self_nonlocal, item: dict[str, object]) -> str:
                normalized = {
                    "label": self_nonlocal._clean_text(item.get("parent_label")),
                    "parent_label": None,
                    "depth": max(0, self_nonlocal._to_sort_int(item.get("depth")) - 1),
                    "role": "menuitem",
                    "aria_label": None,
                    "sibling_index": None,
                }
                return json.dumps(normalized, ensure_ascii=False, sort_keys=True)

            def _is_expand_menu_node(self_nonlocal, item: dict[str, object]) -> bool:
                entry_type = self_nonlocal._clean_text(item.get("entry_type") or item.get("interaction_type"))
                normalized_entry_type = entry_type.lower().replace("-", "_") if entry_type is not None else None
                aria_expanded = self_nonlocal._clean_text(item.get("aria_expanded"))
                return normalized_entry_type in {"menu_expand", "tree_expand", "expand_panel"} or aria_expanded == "false"

            def _is_route_less_leaf_menu_node(self_nonlocal, item: dict[str, object]) -> bool:
                route_path = self_nonlocal._normalize_path(item.get("route_path") or item.get("page_route_path"))
                if route_path is not None:
                    return False
                return not self_nonlocal._is_expand_menu_node(item)

            def _to_sort_int(self_nonlocal, value: object) -> int:
                if isinstance(value, bool):
                    return 0
                if isinstance(value, int):
                    return value
                if isinstance(value, float):
                    return int(value)
                if isinstance(value, str):
                    stripped = value.strip()
                    if stripped.lstrip("-").isdigit():
                        return int(stripped)
                return 0

            def _to_optional_int(self_nonlocal, value: object) -> int | None:
                if value is None or isinstance(value, bool):
                    return None
                if isinstance(value, int):
                    return value
                if isinstance(value, float):
                    return int(value)
                if isinstance(value, str):
                    stripped = value.strip()
                    if stripped.lstrip("-").isdigit():
                        return int(stripped)
                return None

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
        auth_service=None,
        page_discovery_extractor: PageDiscoveryProtocol | None = None,
        router_extractor: RouterRuntimeExtractor | None = None,
        dom_menu_extractor: DomMenuExtractor | None = None,
        state_probe_extractor: StateProbeExtractor | None = None,
    ) -> None:
        self.session = session
        self.browser_factory = browser_factory
        self.auth_service = auth_service
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
        auto_commit: bool = True,
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

        system_credential = await self._load_system_credential(system_id=system_id)
        entry_url = _derive_crawl_entry_url(
            base_url=system.base_url,
            login_url=system_credential.login_url if system_credential is not None else None,
        )
        combined = await self._extract_crawl_once(
            system=system,
            auth_state=auth_state,
            crawl_scope=crawl_scope,
            entry_url=entry_url,
        )
        result_message: str | None = None

        if self._looks_like_stale_auth_state(extraction=combined):
            if self.auth_service is None:
                combined = combined.model_copy(
                    update={
                        "warning_messages": self._append_warning(
                            combined.warning_messages,
                            "auth_state_stale_detected",
                        )
                    }
                )
            else:
                refresh_result = await self.auth_service.refresh_auth_state(system_id=system_id)
                if refresh_result.status == "success":
                    refreshed_auth_state = await self._load_latest_valid_auth_state(system_id=system_id)
                    if refreshed_auth_state is not None and refreshed_auth_state.storage_state:
                        combined = await self._extract_crawl_once(
                            system=system,
                            auth_state=refreshed_auth_state,
                            crawl_scope=crawl_scope,
                            entry_url=entry_url,
                        )
                        combined = combined.model_copy(
                            update={
                                "warning_messages": self._append_warning(
                                    combined.warning_messages,
                                    "auth_state_auto_refreshed",
                                )
                            }
                        )
                    else:
                        result_message = refresh_result.message or "auth_state_refresh_missing"
                        combined = combined.model_copy(
                            update={
                                "warning_messages": self._append_warning(
                                    combined.warning_messages,
                                    "auth_state_refresh_failed",
                                )
                            }
                        )
                else:
                    result_message = refresh_result.message
                    combined = combined.model_copy(
                        update={
                            "warning_messages": self._append_warning(
                                combined.warning_messages,
                                "auth_state_refresh_failed",
                            )
                        }
                    )

        return await self._persist_crawl_result(
            system_id=system_id,
            crawl_scope=crawl_scope,
            system_framework=system.framework_type,
            extraction=combined,
            message=result_message,
            auto_commit=auto_commit,
        )

    async def _extract_crawl_once(
        self,
        *,
        system: System,
        auth_state: AuthState,
        crawl_scope: str,
        entry_url: str,
    ) -> CrawlExtractionResult:
        try:
            browser_session = await self.browser_factory.open_context(
                base_url=system.base_url,
                storage_state=auth_state.storage_state,
                entry_url=entry_url,
            )
        except TypeError as exc:
            if "entry_url" not in str(exc):
                raise
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
                page_candidates=page_discovery_result.pages,
                navigation_targets=page_discovery_result.navigation_targets,
            )
        finally:
            await browser_session.close()

        return self._combine_results(
            system=system,
            discovery=page_discovery_result,
            dom=dom_result,
            probe=probe_result,
        )

    async def _persist_crawl_result(
        self,
        *,
        system_id: UUID,
        crawl_scope: str,
        system_framework: str,
        extraction: CrawlExtractionResult,
        message: str | None = None,
        auto_commit: bool = True,
    ) -> CrawlRunResult:
        snapshot = self._build_snapshot(
            system_id=system_id,
            crawl_scope=crawl_scope,
            system_framework=system_framework,
            extraction=extraction,
        )
        self.session.add(snapshot)
        await self._flush()

        page_map = await self._persist_pages(
            system_id=system_id,
            snapshot_id=snapshot.id,
            pages=extraction.pages,
        )
        await self._persist_menus(
            system_id=system_id,
            snapshot_id=snapshot.id,
            menus=extraction.menus,
            page_map=page_map,
        )
        await self._persist_elements(
            system_id=system_id,
            snapshot_id=snapshot.id,
            elements=extraction.elements,
            page_map=page_map,
        )

        snapshot.finished_at = utcnow()
        if auto_commit:
            await self._commit()

        return CrawlRunResult(
            system_id=system_id,
            status="success",
            snapshot_id=snapshot.id,
            pages_saved=len(page_map),
            menus_saved=len(extraction.menus),
            elements_saved=len(extraction.elements),
            message=message,
            failure_reason=extraction.failure_reason,
            warning_messages=extraction.warning_messages,
            degraded=extraction.degraded,
        )

    def _combine_results(
        self,
        *,
        system,
        discovery: CrawlExtractionResult,
        dom: CrawlExtractionResult,
        probe: CrawlExtractionResult,
    ) -> CrawlExtractionResult:
        representative_elements = self._merge_representative_elements(
            dom_elements=dom.elements,
            probe_elements=probe.elements,
        )
        page_candidates: dict[str, PageCandidate] = {}
        for candidate in discovery.pages + dom.pages + probe.pages:
            existing = page_candidates.get(candidate.route_path)
            page_candidates[candidate.route_path] = (
                candidate if existing is None else self._merge_page_candidate(existing=existing, incoming=candidate)
            )

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
        failure_reason = discovery.failure_reason or dom.failure_reason
        if failure_reason is None and len(page_candidates) == 0:
            failure_reason = probe.failure_reason
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

    def _merge_representative_elements(
        self,
        *,
        dom_elements: list[ElementCandidate],
        probe_elements: list[ElementCandidate],
    ) -> list[ElementCandidate]:
        merged: dict[str, ElementCandidate] = {}
        ordered_keys: list[str] = []
        for candidate in [*dom_elements, *probe_elements]:
            if not candidate.state_signature:
                continue
            key = self._build_representative_element_key(candidate)
            existing = merged.get(key)
            if existing is None:
                merged[key] = candidate
                ordered_keys.append(key)
                continue
            merged[key] = existing.model_copy(
                update={
                    "element_type": candidate.element_type or existing.element_type,
                    "element_role": candidate.element_role or existing.element_role,
                    "element_text": candidate.element_text or existing.element_text,
                    "attributes": self._merge_dict(existing.attributes, candidate.attributes),
                    "playwright_locator": candidate.playwright_locator or existing.playwright_locator,
                    "state_context": self._merge_dict(existing.state_context, candidate.state_context),
                    "locator_candidates": self._merge_locator_candidates(
                        existing.locator_candidates,
                        candidate.locator_candidates,
                    ),
                    "stability_score": candidate.stability_score
                    if candidate.stability_score is not None
                    else existing.stability_score,
                    "usage_description": candidate.usage_description or existing.usage_description,
                    "materialized_by": candidate.materialized_by or existing.materialized_by,
                    "navigation_diagnostics": self._merge_dict(
                        existing.navigation_diagnostics,
                        candidate.navigation_diagnostics,
                    ),
                }
            )
        return [merged[key] for key in ordered_keys]

    def _merge_page_candidate(self, *, existing: PageCandidate, incoming: PageCandidate) -> PageCandidate:
        return existing.model_copy(
            update={
                "page_title": existing.page_title or incoming.page_title,
                "page_summary": existing.page_summary or incoming.page_summary,
                "keywords": self._merge_dict(existing.keywords, incoming.keywords),
                "discovery_sources": sorted({*existing.discovery_sources, *incoming.discovery_sources}),
                "entry_candidates": self._merge_entry_candidates(
                    existing.entry_candidates,
                    incoming.entry_candidates,
                ),
                "context_constraints": self._merge_dict(
                    existing.context_constraints,
                    incoming.context_constraints,
                ),
                "navigation_diagnostics": self._merge_dict(
                    existing.navigation_diagnostics,
                    incoming.navigation_diagnostics,
                ),
            }
        )

    def _build_representative_element_key(self, candidate: ElementCandidate) -> str:
        payload = {
            "page_route_path": candidate.page_route_path,
            "state_signature": candidate.state_signature,
            "element_type": candidate.element_type,
            "element_role": candidate.element_role,
            "element_text": candidate.element_text,
            "playwright_locator_fallback": (
                candidate.playwright_locator
                if not candidate.element_role and not candidate.element_text
                else None
            ),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _merge_dict(
        self,
        base: dict[str, object] | None,
        incoming: dict[str, object] | None,
    ) -> dict[str, object] | None:
        if not base and not incoming:
            return None
        merged: dict[str, object] = {}
        if isinstance(base, dict):
            merged.update(base)
        if isinstance(incoming, dict):
            merged.update(incoming)
        return merged

    def _merge_locator_candidates(
        self,
        base: list[dict[str, object]],
        incoming: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        merged: list[dict[str, object]] = []
        seen: set[str] = set()
        for candidate in [*base, *incoming]:
            if not isinstance(candidate, dict):
                continue
            selector = candidate.get("selector")
            strategy_type = candidate.get("strategy_type")
            if not isinstance(selector, str) or not selector.strip():
                continue
            if not isinstance(strategy_type, str) or not strategy_type.strip():
                continue
            normalized = {
                "strategy_type": strategy_type.strip(),
                "selector": selector.strip(),
            }
            serialized = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
            if serialized in seen:
                continue
            seen.add(serialized)
            merged.append(normalized)
        return merged

    def _merge_entry_candidates(
        self,
        base: list[dict[str, object]],
        incoming: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        merged: list[dict[str, object]] = []
        seen: set[str] = set()
        for candidate in [*base, *incoming]:
            if not isinstance(candidate, dict):
                continue
            serialized = json.dumps(candidate, ensure_ascii=False, sort_keys=True)
            if serialized in seen:
                continue
            seen.add(serialized)
            merged.append(dict(candidate))
        return merged

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
            state="draft",
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
                navigation_diagnostics=candidate.navigation_diagnostics,
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
        identity_map: dict[str, MenuNode] = {}
        label_map: dict[str, MenuNode] = {}
        for candidate in menus:
            page = page_map.get(candidate.page_route_path or candidate.route_path or "")
            parent = None
            parent_identity_key = self._serialize_navigation_identity(candidate.parent_navigation_identity)
            if parent_identity_key is not None:
                parent = identity_map.get(parent_identity_key)
            if parent is None:
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
            identity_key = self._serialize_navigation_identity(candidate.navigation_identity)
            if identity_key is not None:
                identity_map[identity_key] = menu

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
                materialized_by=candidate.materialized_by,
                navigation_diagnostics=candidate.navigation_diagnostics,
                stability_score=candidate.stability_score,
                usage_description=candidate.usage_description,
            )
            self.session.add(element)
            await self._flush()

    def _serialize_navigation_identity(self, value: dict[str, object] | None) -> str | None:
        if not isinstance(value, dict):
            return None
        label = value.get("label")
        depth = value.get("depth")
        if not isinstance(label, str) or not label.strip():
            return None
        if isinstance(depth, bool):
            return None
        if not isinstance(depth, int):
            if isinstance(depth, float):
                depth = int(depth)
            elif isinstance(depth, str) and depth.strip().isdigit():
                depth = int(depth.strip())
            else:
                depth = 0
        normalized: dict[str, object] = {
            "label": label.strip(),
            "depth": depth,
        }
        for key in ("role", "aria_label"):
            raw = value.get(key)
            if isinstance(raw, str) and raw.strip():
                normalized[key] = raw.strip()
        sibling_index = value.get("sibling_index")
        if isinstance(sibling_index, bool):
            sibling_index = None
        elif isinstance(sibling_index, float):
            sibling_index = int(sibling_index)
        elif isinstance(sibling_index, str) and sibling_index.strip().isdigit():
            sibling_index = int(sibling_index.strip())
        if isinstance(sibling_index, int):
            normalized["sibling_index"] = sibling_index
        return json.dumps(normalized, ensure_ascii=False, sort_keys=True)

    def _looks_like_stale_auth_state(self, *, extraction: CrawlExtractionResult) -> bool:
        warning_messages = set(extraction.warning_messages)
        if "state_probe_baseline_degraded" not in warning_messages:
            return False
        if extraction.menus:
            return False
        if len(extraction.elements) > 2:
            return False

        page_routes = {
            candidate.route_path.strip().lower()
            for candidate in extraction.pages
            if isinstance(candidate.route_path, str) and candidate.route_path.strip()
        }
        if not page_routes or len(page_routes) > 2:
            return False

        login_markers = ("login", "signin", "sign-in")
        has_login_route = any(any(marker in route for marker in login_markers) for route in page_routes)
        root_like_routes = {"/", "/index", "/home"}
        only_root_or_login = all(
            route in root_like_routes or any(marker in route for marker in login_markers)
            for route in page_routes
        )
        return has_login_route or only_root_or_login

    def _append_warning(self, warnings: list[str], warning: str) -> list[str]:
        if warning in warnings:
            return list(warnings)
        return [*warnings, warning]

    async def _load_latest_valid_auth_state(self, *, system_id: UUID) -> AuthState | None:
        statement = (
            select(AuthState)
            .where(AuthState.system_id == system_id)
            .where(AuthState.status == AuthStateStatus.VALID.value)
            .where(AuthState.is_valid.is_(True))
            .order_by(AuthState.validated_at.desc(), AuthState.id.desc())
        )
        return await self._exec_first(statement)

    async def _load_system_credential(self, *, system_id: UUID) -> SystemCredential | None:
        statement = (
            select(SystemCredential)
            .where(SystemCredential.system_id == system_id)
            .order_by(SystemCredential.id.desc())
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
