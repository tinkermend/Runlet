from __future__ import annotations

from typing import Protocol

from app.domains.crawler_service.schemas import CrawlExtractionResult


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
