from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session, select

from app.domains.asset_compiler.check_templates import build_standard_checks
from app.domains.asset_compiler.fingerprints import build_page_fingerprint, compare_fingerprints
from app.domains.asset_compiler.module_plan_builder import build_module_plan
from app.domains.asset_compiler.reconciliation import (
    ActiveCheckTruth,
    ActivePageTruth,
    QUALITY_GATE_MIN_SCORE,
    build_blocking_dependency_json,
    build_current_snapshot_truth,
    evaluate_retirement_quality_gate,
    reconcile_retirement_decisions,
)
from app.domains.asset_compiler.schemas import CompileSnapshotResult
from app.infrastructure.db.models.assets import (
    AssetReconciliationAudit,
    AssetSnapshot,
    IntentAlias,
    ModulePlan,
    PageAsset,
    PageCheck,
)
from app.infrastructure.db.models.crawl import CrawlSnapshot, MenuNode, Page, PageElement
from app.infrastructure.db.models.jobs import PublishedJob
from app.infrastructure.db.models.systems import System
from app.shared.enums import AssetLifecycleStatus, AssetStatus, PublishedJobState


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
        snapshot_truth = build_current_snapshot_truth(
            pages=pages,
            menus=menus,
            elements=elements,
        )

        menus_by_page = _group_by_page(menus)
        elements_by_page = _group_by_page(elements)

        assets_created = 0
        assets_updated = 0
        checks_created = 0
        checks_updated = 0
        page_asset_ids: list[UUID] = []
        page_check_ids: list[UUID] = []
        drift_states: list[AssetStatus] = []
        reactivated_check_ids: list[UUID] = []

        high_quality_full_snapshot = _is_high_quality_full_snapshot(snapshot)
        active_assets_before = await self._load_active_page_assets(system_id=system.id)
        pages_by_id_before = await self._load_pages_by_ids([row.page_id for row in active_assets_before])
        previous_active_page_count = len(
            {
                _normalize_route_path((pages_by_id_before.get(row.page_id).route_path if pages_by_id_before.get(row.page_id) else ""))
                for row in active_assets_before
                if pages_by_id_before.get(row.page_id) is not None
            }
        )
        quality_gate = evaluate_retirement_quality_gate(
            crawl_type=snapshot.crawl_type,
            degraded=snapshot.degraded,
            quality_score=snapshot.quality_score,
            current_page_count=len(snapshot_truth.route_paths),
            previous_active_page_count=previous_active_page_count,
        )

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
                assets_updated += 1

            previous_snapshot = await self._find_latest_asset_snapshot(page_asset_id=page_asset.id)
            diff = compare_fingerprints(
                previous_snapshot_to_dict(previous_snapshot),
                fingerprint,
            )
            page_asset.status = diff.status
            page_asset.drift_status = diff.status
            if high_quality_full_snapshot and page_asset.lifecycle_status != AssetLifecycleStatus.ACTIVE:
                page_asset.lifecycle_status = AssetLifecycleStatus.ACTIVE
                page_asset.retired_reason = None
                page_asset.retired_at = None
                page_asset.retired_by_snapshot_id = None
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
                page_check.blocking_dependency_json = build_blocking_dependency_json(
                    steps_json=module_plan.steps_json,
                    assertion_schema=check_definition.assertion_schema,
                )
                check_was_retired = page_check.lifecycle_status != AssetLifecycleStatus.ACTIVE
                if high_quality_full_snapshot and check_was_retired:
                    page_check.lifecycle_status = AssetLifecycleStatus.ACTIVE
                    page_check.retired_reason = None
                    page_check.retired_at = None
                    page_check.retired_by_snapshot_id = None
                    reactivated_check_ids.append(page_check.id)

                page_check_ids.append(page_check.id)
                if created_check:
                    checks_created += 1
                else:
                    checks_updated += 1

                await self._ensure_intent_aliases(
                    system=system,
                    page=page,
                    asset_key=page_asset.asset_key,
                    check_code=check_definition.check_code,
                )

            page_asset_ids.append(page_asset.id)
            if created_asset:
                assets_created += 1

        active_assets = await self._load_active_page_assets(system_id=system.id)
        active_assets_by_id = {row.id: row for row in active_assets}
        pages_by_id = await self._load_pages_by_ids([row.page_id for row in active_assets])
        active_checks = await self._load_active_page_checks(page_asset_ids=[row.id for row in active_assets])
        active_checks_by_id = {row.id: row for row in active_checks}
        module_plans = await self._load_module_plans(
            module_plan_ids=[
                row.module_plan_id for row in active_checks if row.module_plan_id is not None
            ]
        )

        active_page_truth: list[ActivePageTruth] = []
        for row in active_assets:
            page = pages_by_id.get(row.page_id)
            if page is None:
                continue
            route_path = _normalize_route_path(page.route_path)
            if not route_path:
                continue
            active_page_truth.append(
                ActivePageTruth(
                    page_asset_id=row.id,
                    route_path=route_path,
                )
            )

        active_check_truth: list[ActiveCheckTruth] = []
        for row in active_checks:
            module_plan = module_plans.get(row.module_plan_id) if row.module_plan_id else None
            dependencies = row.blocking_dependency_json
            if dependencies is None:
                dependencies = build_blocking_dependency_json(
                    steps_json=module_plan.steps_json if module_plan else [],
                    assertion_schema=row.assertion_schema,
                )
                row.blocking_dependency_json = dependencies
            active_check_truth.append(
                ActiveCheckTruth(
                    page_check_id=row.id,
                    page_asset_id=row.page_asset_id,
                    blocking_dependency_json=dependencies,
                )
            )

        decisions = reconcile_retirement_decisions(
            active_pages=active_page_truth,
            active_checks=active_check_truth,
            snapshot_truth=snapshot_truth,
            quality_gate=quality_gate,
        )

        now = _utcnow()
        retired_asset_ids: list[UUID] = []
        retired_check_ids: list[UUID] = []
        retire_reason_payloads: list[dict[str, object]] = []
        for decision in decisions:
            retired_check_ids_for_reason: list[UUID] = []
            page_asset = active_assets_by_id.get(decision.page_asset_id)
            if (
                decision.reason == "missing_page"
                and page_asset is not None
                and page_asset.lifecycle_status == AssetLifecycleStatus.ACTIVE
            ):
                page_asset.lifecycle_status = AssetLifecycleStatus.RETIRED_MISSING
                page_asset.retired_reason = "missing_page"
                page_asset.retired_at = now
                page_asset.retired_by_snapshot_id = snapshot.id
                retired_asset_ids.append(page_asset.id)

            for check_id in decision.page_check_ids:
                page_check = active_checks_by_id.get(check_id)
                if page_check is None:
                    continue
                if page_check.lifecycle_status != AssetLifecycleStatus.ACTIVE:
                    continue
                page_check.lifecycle_status = AssetLifecycleStatus.RETIRED_MISSING
                page_check.retired_reason = decision.reason
                page_check.retired_at = now
                page_check.retired_by_snapshot_id = snapshot.id
                retired_check_ids.append(page_check.id)
                retired_check_ids_for_reason.append(page_check.id)

            retire_reason_payloads.append(
                {
                    "reason": decision.reason,
                    "page_asset_id": decision.page_asset_id,
                    "page_check_ids": retired_check_ids_for_reason,
                    "published_job_ids": [],
                }
            )

        retired_asset_ids = _dedupe_uuids(retired_asset_ids)
        retired_check_ids = _dedupe_uuids(retired_check_ids)

        retired_asset_keys = [
                active_assets_by_id[asset_id].asset_key
                for asset_id in retired_asset_ids
                if asset_id in active_assets_by_id
        ]
        retired_check_targets = [
            (
                active_assets_by_id[active_checks_by_id[check_id].page_asset_id].asset_key,
                active_checks_by_id[check_id].check_code,
            )
            for check_id in retired_check_ids
            if check_id in active_checks_by_id
            and active_checks_by_id[check_id].page_asset_id in active_assets_by_id
        ]
        alias_ids_to_disable = await self._query_alias_ids_to_disable(
            retired_asset_keys=retired_asset_keys,
            retired_check_targets=retired_check_targets,
        )
        published_jobs_to_pause = await self._query_published_jobs_to_pause(
            page_check_ids=retired_check_ids,
        )
        published_job_ids_to_pause = [row.id for row in published_jobs_to_pause]
        retired_check_id_set = set(retired_check_ids)
        resume_check_ids = [
            check_id for check_id in _dedupe_uuids(reactivated_check_ids) if check_id not in retired_check_id_set
        ]
        resume_check_targets = [
            (
                active_assets_by_id[active_checks_by_id[check_id].page_asset_id].asset_key,
                active_checks_by_id[check_id].check_code,
            )
            for check_id in resume_check_ids
            if check_id in active_checks_by_id
            and active_checks_by_id[check_id].page_asset_id in active_assets_by_id
        ]
        alias_ids_to_enable = await self._query_alias_ids_to_enable(
            reactivated_check_targets=resume_check_targets,
        )
        published_jobs_to_resume = await self._query_published_jobs_to_resume(
            page_check_ids=resume_check_ids,
        )
        published_job_ids_to_resume = [row.id for row in published_jobs_to_resume]

        published_job_ids_by_check_id: dict[UUID, list[UUID]] = defaultdict(list)
        for row in published_jobs_to_pause:
            published_job_ids_by_check_id[row.page_check_id].append(row.id)
        for reason_payload in retire_reason_payloads:
            check_ids = reason_payload.get("page_check_ids")
            if not isinstance(check_ids, list):
                continue
            reason_payload["published_job_ids"] = sorted(
                {
                    job_id
                    for check_id in check_ids
                    if isinstance(check_id, UUID)
                    for job_id in published_job_ids_by_check_id.get(check_id, [])
                },
                key=str,
            )

        if quality_gate.warning_payload is not None:
            retire_reason_payloads.append(
                {
                    "reason": "quality_gate_blocked",
                    "page_asset_id": None,
                    "page_check_ids": [],
                    "published_job_ids": [],
                    "warning": quality_gate.warning_payload,
                }
            )

        self.session.add(
            AssetReconciliationAudit(
                snapshot_id=snapshot.id,
                retired_asset_ids=[str(asset_id) for asset_id in retired_asset_ids],
                retired_check_ids=[str(check_id) for check_id in retired_check_ids],
                disabled_alias_ids=[str(alias_id) for alias_id in alias_ids_to_disable],
                paused_published_job_ids=[str(job_id) for job_id in published_job_ids_to_pause],
                retire_reasons=retire_reason_payloads,
            )
        )

        await self._commit()
        return CompileSnapshotResult(
            snapshot_id=snapshot.id,
            status="success",
            assets_created=assets_created,
            assets_updated=assets_updated,
            assets_retired=len(retired_asset_ids),
            checks_created=checks_created,
            checks_updated=checks_updated,
            checks_retired=len(retired_check_ids),
            drift_state=_max_drift_state(drift_states),
            asset_ids=page_asset_ids,
            check_ids=page_check_ids,
            alias_disable_decision_count=len(alias_ids_to_disable),
            alias_enable_decision_count=len(alias_ids_to_enable),
            published_job_pause_decision_count=len(published_job_ids_to_pause),
            published_job_resume_decision_count=len(published_job_ids_to_resume),
            alias_ids_to_disable=alias_ids_to_disable,
            alias_ids_to_enable=alias_ids_to_enable,
            published_job_ids_to_pause=published_job_ids_to_pause,
            published_job_ids_to_resume=published_job_ids_to_resume,
            retire_reasons=retire_reason_payloads,
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

    async def _load_active_page_assets(self, *, system_id: UUID) -> list[PageAsset]:
        return await self._exec_all(
            select(PageAsset)
            .where(PageAsset.system_id == system_id)
            .where(PageAsset.lifecycle_status == AssetLifecycleStatus.ACTIVE)
            .order_by(PageAsset.id)
        )

    async def _load_active_page_checks(self, *, page_asset_ids: list[UUID]) -> list[PageCheck]:
        if not page_asset_ids:
            return []
        return await self._exec_all(
            select(PageCheck)
            .where(PageCheck.page_asset_id.in_(page_asset_ids))
            .where(PageCheck.lifecycle_status == AssetLifecycleStatus.ACTIVE)
            .order_by(PageCheck.id)
        )

    async def _load_pages_by_ids(self, page_ids: list[UUID]) -> dict[UUID, Page]:
        if not page_ids:
            return {}
        pages = await self._exec_all(
            select(Page)
            .where(Page.id.in_(page_ids))
            .order_by(Page.id)
        )
        return {row.id: row for row in pages}

    async def _load_module_plans(self, *, module_plan_ids: list[UUID]) -> dict[UUID, ModulePlan]:
        if not module_plan_ids:
            return {}
        module_plans = await self._exec_all(
            select(ModulePlan)
            .where(ModulePlan.id.in_(module_plan_ids))
            .order_by(ModulePlan.id)
        )
        return {row.id: row for row in module_plans}

    async def _query_alias_ids_to_disable(
        self,
        *,
        retired_asset_keys: list[str],
        retired_check_targets: list[tuple[str, str]],
    ) -> list[UUID]:
        check_target_set = {
            (asset_key, check_code)
            for asset_key, check_code in retired_check_targets
            if asset_key and check_code
        }
        candidate_asset_keys = set(retired_asset_keys) | {asset_key for asset_key, _ in check_target_set}
        if not candidate_asset_keys:
            return []
        aliases = await self._exec_all(
            select(IntentAlias)
            .where(IntentAlias.asset_key.in_(sorted(candidate_asset_keys)))
            .where(IntentAlias.is_active.is_(True))
            .order_by(IntentAlias.id)
        )
        retired_asset_key_set = {asset_key for asset_key in retired_asset_keys if asset_key}
        selected_alias_ids: list[UUID] = []
        for alias in aliases:
            if alias.asset_key in retired_asset_key_set:
                selected_alias_ids.append(alias.id)
                continue
            if (alias.asset_key, alias.check_alias) in check_target_set:
                selected_alias_ids.append(alias.id)
        return selected_alias_ids

    async def _query_alias_ids_to_enable(
        self,
        *,
        reactivated_check_targets: list[tuple[str, str]],
    ) -> list[UUID]:
        check_target_set = {
            (asset_key, check_code)
            for asset_key, check_code in reactivated_check_targets
            if asset_key and check_code
        }
        if not check_target_set:
            return []
        asset_keys = sorted({asset_key for asset_key, _ in check_target_set})
        aliases = await self._exec_all(
            select(IntentAlias)
            .where(IntentAlias.asset_key.in_(asset_keys))
            .where(IntentAlias.is_active.is_(False))
            .order_by(IntentAlias.id)
        )
        selected_alias_ids: list[UUID] = []
        for alias in aliases:
            if (alias.asset_key, alias.check_alias) in check_target_set:
                selected_alias_ids.append(alias.id)
        return selected_alias_ids

    async def _query_published_jobs_to_pause(self, *, page_check_ids: list[UUID]) -> list[PublishedJob]:
        if not page_check_ids:
            return []
        return await self._exec_all(
            select(PublishedJob)
            .where(PublishedJob.page_check_id.in_(page_check_ids))
            .where(PublishedJob.state == PublishedJobState.ACTIVE)
            .order_by(PublishedJob.id)
        )

    async def _query_published_jobs_to_resume(self, *, page_check_ids: list[UUID]) -> list[PublishedJob]:
        if not page_check_ids:
            return []
        return await self._exec_all(
            select(PublishedJob)
            .where(PublishedJob.page_check_id.in_(page_check_ids))
            .where(PublishedJob.state == PublishedJobState.PAUSED)
            .order_by(PublishedJob.id)
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
    if not states:
        return AssetStatus.SAFE
    if AssetStatus.STALE in states:
        return AssetStatus.STALE
    if AssetStatus.SUSPECT in states:
        return AssetStatus.SUSPECT
    return AssetStatus.SAFE


def _normalize_route_path(route_path: object) -> str:
    if route_path is None:
        return ""
    return str(route_path).strip()


def _is_high_quality_full_snapshot(snapshot: CrawlSnapshot) -> bool:
    if snapshot.crawl_type != "full":
        return False
    if snapshot.degraded:
        return False
    if snapshot.quality_score is None:
        return False
    return snapshot.quality_score >= QUALITY_GATE_MIN_SCORE


def _dedupe_uuids(values: list[UUID]) -> list[UUID]:
    deduped: list[UUID] = []
    seen: set[UUID] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
