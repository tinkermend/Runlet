from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.api.deps_auth import require_console_user
from app.domains.control_plane.console_schemas import (
    CHECK_TYPE_LABELS,
    AssetDetail,
    AssetItem,
    PageGroup,
    SystemAssetGroup,
)
from app.infrastructure.db.console_session import get_console_db
from app.infrastructure.db.models.assets import PageAsset, PageCheck
from app.infrastructure.db.models.crawl import CrawlSnapshot, Page
from app.infrastructure.db.models.identity import User
from app.infrastructure.db.models.systems import System

router = APIRouter(prefix="/assets", tags=["console-assets"])

ConsoleDep = Annotated[Session, Depends(get_console_db)]


def _check_type_label(asset_key: str, check_codes: list[str]) -> str:
    """Derive a human-friendly label from check codes or asset key."""
    for code in check_codes:
        if code in CHECK_TYPE_LABELS:
            return CHECK_TYPE_LABELS[code]
    # Fallback: try to match asset_key suffix
    for key, label in CHECK_TYPE_LABELS.items():
        if key in asset_key:
            return label
    return check_codes[0] if check_codes else asset_key


def _asset_status_label(asset: PageAsset) -> str:
    status = asset.status
    if hasattr(status, "value"):
        return status.value
    return str(status)


def _get_check_codes_for_asset(session: Session, asset_id: UUID) -> list[str]:
    checks = session.exec(
        select(PageCheck).where(PageCheck.page_asset_id == asset_id)
    ).all()
    return [c.check_code for c in checks]


def _get_active_snapshot(session: Session, system_id: UUID) -> CrawlSnapshot | None:
    return session.exec(
        select(CrawlSnapshot)
        .where(CrawlSnapshot.system_id == system_id)
        .where(CrawlSnapshot.state == "active")
        .order_by(CrawlSnapshot.activated_at.desc(), CrawlSnapshot.started_at.desc(), CrawlSnapshot.id.desc())
    ).first()


def _resolve_active_page_for_asset(
    session: Session,
    *,
    asset: PageAsset,
    fallback_page: Page | None,
) -> Page | None:
    if fallback_page is None or not fallback_page.route_path:
        return None
    active_snapshot = _get_active_snapshot(session, asset.system_id)
    if active_snapshot is None:
        return None
    return session.exec(
        select(Page)
        .where(Page.system_id == asset.system_id)
        .where(Page.snapshot_id == active_snapshot.id)
        .where(Page.route_path == fallback_page.route_path)
        .order_by(Page.id)
    ).first()


@router.get("/", response_model=list[SystemAssetGroup])
def list_assets(
    session: ConsoleDep,
    _: User = Depends(require_console_user),
) -> list[SystemAssetGroup]:
    assets = session.exec(select(PageAsset)).all()

    # Group: system_id -> page_id -> list[PageAsset]
    system_map: dict[UUID, dict[UUID, list[PageAsset]]] = {}
    for asset in assets:
        system_map.setdefault(asset.system_id, {}).setdefault(asset.page_id, []).append(asset)

    result: list[SystemAssetGroup] = []
    for system_id, page_map in system_map.items():
        system = session.get(System, system_id)
        if not system:
            continue

        pages: list[PageGroup] = []
        for page_id, page_assets in page_map.items():
            page = session.get(Page, page_id)
            active_page = _resolve_active_page_for_asset(
                session,
                asset=page_assets[0],
                fallback_page=page,
            )
            display_page = active_page or page
            page_name = display_page.page_title or display_page.route_path if display_page else str(page_id)

            asset_items: list[AssetItem] = []
            for asset in page_assets:
                check_codes = _get_check_codes_for_asset(session, asset.id)
                label = _check_type_label(asset.asset_key, check_codes)
                asset_items.append(
                    AssetItem(
                        id=asset.id,
                        check_type_label=label,
                        version=asset.asset_version,
                        status=_asset_status_label(asset),
                    )
                )

            pages.append(PageGroup(page_name=page_name, assets=asset_items))

        result.append(
            SystemAssetGroup(
                system_id=system_id,
                system_name=system.name,
                pages=pages,
            )
        )

    return result


@router.get("/{asset_id}", response_model=AssetDetail)
def get_asset(
    asset_id: UUID,
    session: ConsoleDep,
    _: User = Depends(require_console_user),
) -> AssetDetail:
    asset = session.get(PageAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    page = session.get(Page, asset.page_id)
    active_page = _resolve_active_page_for_asset(session, asset=asset, fallback_page=page)
    display_page = active_page or page
    page_name = display_page.page_title or display_page.route_path if display_page else str(asset.page_id)

    system = session.get(System, asset.system_id)
    system_name = system.name if system else str(asset.system_id)

    check_codes = _get_check_codes_for_asset(session, asset.id)
    label = _check_type_label(asset.asset_key, check_codes)

    # Raw facts always read from the current active page when one exists.
    raw_facts: dict | None = None
    if active_page:
        from app.infrastructure.db.models.crawl import MenuNode, PageElement

        menu_nodes = session.exec(
            select(MenuNode)
            .where(MenuNode.page_id == active_page.id)
            .where(MenuNode.snapshot_id == active_page.snapshot_id)
        ).all()
        page_elements = session.exec(
            select(PageElement)
            .where(PageElement.page_id == active_page.id)
            .where(PageElement.snapshot_id == active_page.snapshot_id)
        ).all()

        if menu_nodes or page_elements:
            raw_facts = {
                "menu_nodes": [
                    {
                        "id": str(n.id),
                        "label": n.label,
                        "route_path": n.route_path,
                        "depth": n.depth,
                        "playwright_locator": n.playwright_locator,
                    }
                    for n in menu_nodes
                ],
                "page_elements": [
                    {
                        "id": str(e.id),
                        "element_type": e.element_type,
                        "element_role": e.element_role,
                        "element_text": e.element_text,
                        "playwright_locator": e.playwright_locator,
                    }
                    for e in page_elements
                ],
            }

    collected_at = active_page.crawled_at if active_page else None

    return AssetDetail(
        id=asset.id,
        page_name=page_name,
        system_name=system_name,
        check_type_label=label,
        version=asset.asset_version,
        status=_asset_status_label(asset),
        collected_at=collected_at,
        raw_facts=raw_facts,
    )
