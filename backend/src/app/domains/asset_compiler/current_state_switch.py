from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session, select

from app.domains.asset_compiler.current_state_diff import (
    PageSemanticFingerprint,
    compare_semantic_states,
)
from app.infrastructure.db.models.crawl import CrawlSnapshot, MenuNode, Page, PageElement
from app.infrastructure.db.models.crawl_history import CrawlSnapshotHist


@dataclass(frozen=True)
class CurrentStateSwitchResult:
    outcome: str
    active_snapshot_id: UUID | None = None
    archived_snapshot_id: UUID | None = None


async def apply_current_state_switch(
    *,
    session: Session | AsyncSession,
    draft_snapshot_id: UUID,
) -> CurrentStateSwitchResult:
    draft_snapshot = await _get(session, CrawlSnapshot, draft_snapshot_id)
    if draft_snapshot is None:
        raise ValueError(f"crawl snapshot {draft_snapshot_id} not found")

    if draft_snapshot.state == "active":
        return CurrentStateSwitchResult(
            outcome="promoted",
            active_snapshot_id=draft_snapshot.id,
        )
    if draft_snapshot.state != "draft":
        raise ValueError(
            f"crawl snapshot {draft_snapshot_id} must be draft or active, got {draft_snapshot.state}"
        )

    now = _utcnow()
    if not _is_high_quality_snapshot(draft_snapshot):
        draft_snapshot.state = "discarded"
        draft_snapshot.discarded_at = now
        await _flush(session)
        return CurrentStateSwitchResult(outcome="discarded_low_quality")

    active_snapshot = await _load_active_snapshot(
        session=session,
        system_id=draft_snapshot.system_id,
        exclude_snapshot_id=draft_snapshot.id,
    )
    if active_snapshot is None:
        draft_snapshot.state = "active"
        draft_snapshot.activated_at = now
        draft_snapshot.discarded_at = None
        await _flush(session)
        return CurrentStateSwitchResult(
            outcome="promoted",
            active_snapshot_id=draft_snapshot.id,
        )

    active_state = await _load_snapshot_semantic_state(
        session=session,
        snapshot_id=active_snapshot.id,
    )
    draft_state = await _load_snapshot_semantic_state(
        session=session,
        snapshot_id=draft_snapshot.id,
    )
    diff = compare_semantic_states(active=active_state, draft=draft_state)
    if not diff.has_changes:
        draft_snapshot.state = "discarded"
        draft_snapshot.discarded_at = now
        await _flush(session)
        return CurrentStateSwitchResult(
            outcome="discarded_no_change",
            active_snapshot_id=active_snapshot.id,
        )
    archived_snapshot = CrawlSnapshotHist(
        snapshot_id=active_snapshot.id,
        system_id=active_snapshot.system_id,
        crawl_type=active_snapshot.crawl_type,
        framework_detected=active_snapshot.framework_detected,
        quality_score=active_snapshot.quality_score,
        degraded=active_snapshot.degraded,
        state=active_snapshot.state,
        source_active_snapshot_id=active_snapshot.id,
        replaced_by_snapshot_id=draft_snapshot.id,
        archive_reason="semantic_change",
        activated_at=active_snapshot.activated_at,
        discarded_at=active_snapshot.discarded_at,
        failure_reason=active_snapshot.failure_reason,
        warning_messages=list(active_snapshot.warning_messages or []),
        structure_hash=active_snapshot.structure_hash,
        started_at=active_snapshot.started_at,
        finished_at=active_snapshot.finished_at,
    )
    session.add(archived_snapshot)

    active_snapshot.state = "discarded"
    active_snapshot.discarded_at = now
    await _flush(session)
    draft_snapshot.state = "active"
    draft_snapshot.activated_at = now
    draft_snapshot.discarded_at = None
    await _flush(session)
    return CurrentStateSwitchResult(
        outcome="promoted",
        active_snapshot_id=draft_snapshot.id,
        archived_snapshot_id=archived_snapshot.id,
    )


async def _load_active_snapshot(
    *,
    session: Session | AsyncSession,
    system_id: UUID,
    exclude_snapshot_id: UUID,
) -> CrawlSnapshot | None:
    statement = (
        select(CrawlSnapshot)
        .where(CrawlSnapshot.system_id == system_id)
        .where(CrawlSnapshot.state == "active")
        .where(CrawlSnapshot.id != exclude_snapshot_id)
        .order_by(CrawlSnapshot.activated_at.desc(), CrawlSnapshot.started_at.desc(), CrawlSnapshot.id.desc())
    )
    return await _exec_first(session, statement)


async def _load_snapshot_semantic_state(
    *,
    session: Session | AsyncSession,
    snapshot_id: UUID,
) -> list[PageSemanticFingerprint]:
    pages = await _exec_all(
        session,
        select(Page)
        .where(Page.snapshot_id == snapshot_id)
        .order_by(Page.route_path, Page.id),
    )
    menus = await _exec_all(
        session,
        select(MenuNode)
        .where(MenuNode.snapshot_id == snapshot_id)
        .order_by(MenuNode.page_id, MenuNode.depth, MenuNode.sort_order, MenuNode.id),
    )
    elements = await _exec_all(
        session,
        select(PageElement)
        .where(PageElement.snapshot_id == snapshot_id)
        .order_by(PageElement.page_id, PageElement.element_type, PageElement.id),
    )

    menus_by_page: dict[UUID, list[MenuNode]] = defaultdict(list)
    for menu in menus:
        if menu.page_id is None:
            continue
        menus_by_page[menu.page_id].append(menu)

    elements_by_page: dict[UUID, list[PageElement]] = defaultdict(list)
    for element in elements:
        elements_by_page[element.page_id].append(element)

    fingerprints: list[PageSemanticFingerprint] = []
    for page in pages:
        fingerprints.append(
            PageSemanticFingerprint(
                route_path=page.route_path,
                page_title=page.page_title,
                menu_chain=[
                    menu.label
                    for menu in menus_by_page.get(page.id, [])
                    if (menu.label or "").strip()
                ],
                key_elements=[
                    {
                        "kind": element.element_type,
                        "role": element.element_role,
                        "text": _build_element_semantic_text(element),
                    }
                    for element in elements_by_page.get(page.id, [])
                ],
            )
        )
    return fingerprints


def _is_high_quality_snapshot(snapshot: CrawlSnapshot) -> bool:
    if snapshot.crawl_type != "full":
        return False
    if snapshot.degraded:
        return False
    if snapshot.quality_score is None:
        return False
    return snapshot.quality_score >= 0.9


def _build_element_semantic_text(element: PageElement) -> str:
    text = _normalize_text(element.element_text)
    state_signature = _normalize_text(element.state_signature)
    state_context = _normalize_state_context(element.state_context)
    return f"{text}|state={state_signature}|context={state_context}"


async def _get(session: Session | AsyncSession, model, identifier):
    if isinstance(session, AsyncSession):
        return await session.get(model, identifier)
    return session.get(model, identifier)


async def _exec_first(session: Session | AsyncSession, statement):
    if isinstance(session, AsyncSession):
        result = await session.exec(statement)
        return result.first()
    return session.exec(statement).first()


async def _exec_all(session: Session | AsyncSession, statement):
    if isinstance(session, AsyncSession):
        result = await session.exec(statement)
        return result.all()
    return session.exec(statement).all()


async def _flush(session: Session | AsyncSession) -> None:
    if isinstance(session, AsyncSession):
        await session.flush()
        return
    session.flush()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_state_context(value: object) -> str:
    if not isinstance(value, dict) or not value:
        return ""
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
