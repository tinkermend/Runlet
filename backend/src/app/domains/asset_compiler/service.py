from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session, select

from app.domains.asset_compiler.check_templates import build_standard_checks
from app.domains.asset_compiler.fingerprints import build_page_fingerprint, compare_fingerprints
from app.domains.asset_compiler.module_plan_builder import build_module_plan
from app.domains.asset_compiler.schemas import CompileSnapshotResult
from app.infrastructure.db.models.assets import AssetSnapshot, IntentAlias, ModulePlan, PageAsset, PageCheck
from app.infrastructure.db.models.crawl import CrawlSnapshot, MenuNode, Page, PageElement
from app.infrastructure.db.models.systems import System
from app.shared.enums import AssetStatus


class AssetCompilerService:
    def __init__(self, *, session: Session | AsyncSession) -> None:
        self.session = session

    async def compile_snapshot(self, *, snapshot_id: UUID) -> CompileSnapshotResult:
        snapshot = await self._get(CrawlSnapshot, snapshot_id)
        if snapshot is None:
            raise ValueError(f"crawl snapshot {snapshot_id} not found")

        system = await self._get(System, snapshot.system_id)
        if system is None:
            raise ValueError(f"system {snapshot.system_id} not found")

        pages = await self._exec_all(
            select(Page)
            .where(Page.snapshot_id == snapshot_id)
            .order_by(Page.route_path, Page.id)
        )
        menus = await self._exec_all(
            select(MenuNode)
            .where(MenuNode.snapshot_id == snapshot_id)
            .order_by(MenuNode.depth, MenuNode.sort_order, MenuNode.id)
        )
        elements = await self._exec_all(
            select(PageElement)
            .where(PageElement.snapshot_id == snapshot_id)
            .order_by(PageElement.page_id, PageElement.id)
        )

        menus_by_page = _group_by_page(menus)
        elements_by_page = _group_by_page(elements)

        assets_created = 0
        checks_created = 0
        page_asset_ids: list[UUID] = []
        page_check_ids: list[UUID] = []
        drift_states: list[AssetStatus] = []

        for page in pages:
            page_payload = {
                "page": {
                    "route_path": page.route_path,
                    "page_title": page.page_title,
                    "page_summary": page.page_summary,
                },
                "menus": [
                    {
                        "label": menu.label,
                        "route_path": menu.route_path,
                        "depth": menu.depth,
                        "sort_order": menu.sort_order,
                    }
                    for menu in menus_by_page.get(page.id, [])
                ],
                "elements": [
                    {
                        "element_type": element.element_type,
                        "element_role": element.element_role,
                        "element_text": element.element_text,
                        "attributes": element.attributes or {},
                        "playwright_locator": element.playwright_locator,
                        "usage_description": element.usage_description,
                    }
                    for element in elements_by_page.get(page.id, [])
                ],
            }
            fingerprint = build_page_fingerprint(page_payload)

            asset_key = _build_asset_key(system.code, page.route_path, page.page_title)
            page_asset = await self._find_page_asset(system_id=system.id, asset_key=asset_key)
            created_asset = page_asset is None
            if page_asset is None:
                page_asset = PageAsset(
                    system_id=system.id,
                    page_id=page.id,
                    asset_key=asset_key,
                    asset_version=_build_asset_version(snapshot),
                    status=AssetStatus.SAFE,
                    compiled_from_snapshot_id=snapshot.id,
                )
                self.session.add(page_asset)
                await self._flush()
            else:
                page_asset.page_id = page.id
                page_asset.asset_version = _build_asset_version(snapshot)
                page_asset.compiled_from_snapshot_id = snapshot.id

            previous_snapshot = await self._find_latest_asset_snapshot(page_asset_id=page_asset.id)
            diff = compare_fingerprints(
                previous_snapshot_to_dict(previous_snapshot),
                fingerprint,
            )
            page_asset.status = diff.status
            drift_states.append(diff.status)

            asset_snapshot = AssetSnapshot(
                page_asset_id=page_asset.id,
                crawl_snapshot_id=snapshot.id,
                asset_version=page_asset.asset_version,
                structure_hash=fingerprint["structure_hash"],
                navigation_hash=fingerprint["navigation_hash"],
                key_locator_hash=fingerprint["key_locator_hash"],
                semantic_summary_hash=fingerprint["semantic_summary_hash"],
                diff_score_vs_previous=diff.score,
                status=diff.status,
            )
            self.session.add(asset_snapshot)

            has_table = any(element.element_type == "table" for element in elements_by_page.get(page.id, []))
            has_create_action = any(
                _suggests_create_action(element.element_text)
                for element in elements_by_page.get(page.id, [])
            )
            page_context = {
                "system_code": system.code,
                "page_title": page.page_title,
                "route_path": page.route_path,
                "menu_chain": [menu.label for menu in menus_by_page.get(page.id, []) if menu.label],
                "has_table": has_table,
            }
            standard_checks = build_standard_checks(
                page_summary=page.page_summary,
                has_table=has_table,
                has_create_action=has_create_action,
            )

            for check_definition in standard_checks:
                module_plan_draft = build_module_plan(
                    check_code=check_definition.check_code,
                    page_context=page_context,
                )
                module_plan = ModulePlan(
                    page_asset_id=page_asset.id,
                    check_code=check_definition.check_code,
                    plan_version=module_plan_draft.plan_version,
                    steps_json=module_plan_draft.steps_json,
                )
                self.session.add(module_plan)
                await self._flush()

                page_check = await self._find_page_check(
                    page_asset_id=page_asset.id,
                    check_code=check_definition.check_code,
                )
                created_check = page_check is None
                if page_check is None:
                    page_check = PageCheck(
                        page_asset_id=page_asset.id,
                        check_code=check_definition.check_code,
                        goal=check_definition.goal,
                    )
                    self.session.add(page_check)
                    await self._flush()

                page_check.goal = check_definition.goal
                page_check.input_schema = check_definition.input_schema
                page_check.assertion_schema = check_definition.assertion_schema
                page_check.module_plan_id = module_plan.id

                page_check_ids.append(page_check.id)
                if created_check:
                    checks_created += 1

                await self._ensure_intent_aliases(
                    system=system,
                    page=page,
                    asset_key=page_asset.asset_key,
                    check_code=check_definition.check_code,
                )

            page_asset_ids.append(page_asset.id)
            if created_asset:
                assets_created += 1

        await self._commit()
        return CompileSnapshotResult(
            snapshot_id=snapshot.id,
            status="success",
            assets_created=assets_created,
            checks_created=checks_created,
            drift_state=_max_drift_state(drift_states),
            asset_ids=page_asset_ids,
            check_ids=page_check_ids,
        )

    async def _find_page_asset(self, *, system_id: UUID, asset_key: str) -> PageAsset | None:
        return await self._exec_first(
            select(PageAsset)
            .where(PageAsset.system_id == system_id)
            .where(PageAsset.asset_key == asset_key)
            .order_by(PageAsset.id)
        )

    async def _find_page_check(self, *, page_asset_id: UUID, check_code: str) -> PageCheck | None:
        return await self._exec_first(
            select(PageCheck)
            .where(PageCheck.page_asset_id == page_asset_id)
            .where(PageCheck.check_code == check_code)
            .order_by(PageCheck.id)
        )

    async def _find_latest_asset_snapshot(self, *, page_asset_id: UUID) -> AssetSnapshot | None:
        return await self._exec_first(
            select(AssetSnapshot)
            .where(AssetSnapshot.page_asset_id == page_asset_id)
            .order_by(AssetSnapshot.id.desc())
        )

    async def _ensure_intent_aliases(
        self,
        *,
        system: System,
        page: Page,
        asset_key: str,
        check_code: str,
    ) -> None:
        candidates = [
            (system.code, page.page_title or page.route_path, page.route_path),
            (system.name, page.page_title or page.route_path, page.route_path),
        ]
        for system_alias, page_alias, route_hint in candidates:
            existing = await self._exec_first(
                select(IntentAlias)
                .where(IntentAlias.system_alias == system_alias)
                .where(IntentAlias.page_alias == page_alias)
                .where(IntentAlias.check_alias == check_code)
                .where(IntentAlias.asset_key == asset_key)
            )
            if existing is not None:
                existing.route_hint = route_hint
                existing.confidence = 1.0
                existing.source = "asset_compiler"
                continue

            self.session.add(
                IntentAlias(
                    system_alias=system_alias,
                    page_alias=page_alias,
                    check_alias=check_code,
                    route_hint=route_hint,
                    asset_key=asset_key,
                    confidence=1.0,
                    source="asset_compiler",
                )
            )

    async def _get(self, model, identifier):
        if isinstance(self.session, AsyncSession):
            return await self.session.get(model, identifier)
        return self.session.get(model, identifier)

    async def _exec_first(self, statement):
        if isinstance(self.session, AsyncSession):
            result = await self.session.exec(statement)
            return result.first()
        return self.session.exec(statement).first()

    async def _exec_all(self, statement):
        if isinstance(self.session, AsyncSession):
            result = await self.session.exec(statement)
            return result.all()
        return self.session.exec(statement).all()

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


def _group_by_page(records: Iterable[Any]) -> dict[UUID, list[Any]]:
    grouped: dict[UUID, list[Any]] = {}
    for record in records:
        grouped.setdefault(record.page_id, []).append(record)
    return grouped


def _build_asset_key(system_code: str, route_path: str, page_title: str | None) -> str:
    route_segments = [segment for segment in route_path.strip("/").split("/") if segment]
    if route_segments:
        return ".".join([system_code.lower(), *route_segments]).replace("-", "_")
    fallback = (page_title or "page").strip().replace(" ", "_")
    return ".".join([system_code.lower(), fallback.lower()])


def _build_asset_version(snapshot: CrawlSnapshot) -> str:
    if snapshot.started_at is not None:
        return snapshot.started_at.strftime("%Y%m%d%H%M%S")
    return snapshot.id.hex[:14]


def _suggests_create_action(label: str | None) -> bool:
    if not label:
        return False
    return any(keyword in label for keyword in ("新增", "新建", "创建"))


def previous_snapshot_to_dict(previous_snapshot: AssetSnapshot | None) -> dict[str, str] | None:
    if previous_snapshot is None:
        return None
    return {
        "navigation_hash": previous_snapshot.navigation_hash,
        "key_locator_hash": previous_snapshot.key_locator_hash,
        "semantic_summary_hash": previous_snapshot.semantic_summary_hash,
        "structure_hash": previous_snapshot.structure_hash,
    }


def _max_drift_state(states: list[AssetStatus]) -> AssetStatus:
    if AssetStatus.STALE in states:
        return AssetStatus.STALE
    if AssetStatus.SUSPECT in states:
        return AssetStatus.SUSPECT
    return AssetStatus.SAFE
