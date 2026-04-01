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
    NullDomMenuExtractor,
)
from app.domains.crawler_service.extractors.router_runtime import (
    NullRouterRuntimeExtractor,
    RouterRuntimeExtractor,
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
    async def close(self) -> None: ...


class BrowserFactory(Protocol):
    async def open_context(
        self,
        *,
        base_url: str,
        storage_state: dict[str, object],
    ) -> BrowserSession: ...


class PlaywrightBrowserFactory:
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

        class _Session:
            async def close(self_nonlocal) -> None:
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
        router_extractor: RouterRuntimeExtractor | None = None,
        dom_menu_extractor: DomMenuExtractor | None = None,
    ) -> None:
        self.session = session
        self.browser_factory = browser_factory
        self.router_extractor = router_extractor or NullRouterRuntimeExtractor()
        self.dom_menu_extractor = dom_menu_extractor or NullDomMenuExtractor()

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
            runtime_result = await self.router_extractor.extract(
                browser_session=browser_session,
                system=system,
                crawl_scope=crawl_scope,
            )
            dom_result = await self.dom_menu_extractor.extract(
                browser_session=browser_session,
                system=system,
                crawl_scope=crawl_scope,
            )
        finally:
            await browser_session.close()

        combined = self._combine_results(system=system, runtime=runtime_result, dom=dom_result)
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
        )

    def _combine_results(
        self,
        *,
        system,
        runtime: CrawlExtractionResult,
        dom: CrawlExtractionResult,
    ) -> CrawlExtractionResult:
        page_candidates: dict[str, PageCandidate] = {}
        for candidate in runtime.pages + dom.pages:
            page_candidates[candidate.route_path] = candidate

        for menu in dom.menus:
            route_path = menu.page_route_path or menu.route_path
            if route_path and route_path not in page_candidates:
                page_candidates[route_path] = PageCandidate(route_path=route_path, page_title=menu.label)

        for element in dom.elements:
            if element.page_route_path not in page_candidates:
                page_candidates[element.page_route_path] = PageCandidate(route_path=element.page_route_path)

        quality_candidates = [value for value in (runtime.quality_score, dom.quality_score) if value is not None]
        quality_score = max(quality_candidates) if quality_candidates else None

        return CrawlExtractionResult(
            framework_detected=runtime.framework_detected or dom.framework_detected or system.framework_type,
            quality_score=quality_score,
            pages=list(page_candidates.values()),
            menus=dom.menus,
            elements=dom.elements,
        )

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
            degraded=len(extraction.pages) == 0,
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
