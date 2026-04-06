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
from app.domains.asset_compiler.locator_bundles import build_locator_bundle
from app.domains.asset_compiler.module_plan_builder import build_module_plan
from app.domains.asset_compiler.navigation_aliases import NavigationAliasDraft, build_navigation_aliases
from app.domains.asset_compiler.reconciliation import (
    ActiveCheckTruth,
    ActivePageTruth,
    QUALITY_GATE_MIN_SCORE,
    build_blocking_dependency_json,
    build_current_snapshot_truth,
    evaluate_retirement_quality_gate,
    reconcile_retirement_decisions,
)
from app.domains.asset_compiler.schemas import CompileSnapshotResult, LocatorBundle
from app.infrastructure.db.models.assets import (
    AssetReconciliationAudit,
    AssetSnapshot,
    IntentAlias,
    ModulePlan,
    PageAsset,
    PageCheck,
    PageNavigationAlias,
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
        menus_by_id = {menu.id: menu for menu in menus}

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
            default_state_signature = _build_default_state_signature(page.route_path)
            normalized_elements = [
                _build_normalized_element(
                    element=element,
                    default_state_signature=default_state_signature,
                )
                for element in elements_by_page.get(page.id, [])
            ]
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
                "elements": normalized_elements,
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

            has_table = any(
                _normalize_text(element.get("element_type")) == "table"
                for element in normalized_elements
            )
            has_create_action = any(
                _suggests_create_action(_normalize_text(element.get("element_text")))
                for element in normalized_elements
            )
            page_context = {
                "system_code": system.code,
                "page_title": page.page_title,
                "route_path": page.route_path,
                "menu_chain": [menu.label for menu in menus_by_page.get(page.id, []) if menu.label],
                "has_table": has_table,
                "default_state_signature": default_state_signature,
            }
            standard_checks = build_standard_checks(
                page_summary=page.page_summary,
                has_table=has_table,
                has_create_action=has_create_action,
                representative_states=_collect_representative_states(normalized_elements),
                default_state_signature=default_state_signature,
            )

            for check_definition in standard_checks:
                check_state_signature = check_definition.state_signature or default_state_signature
                locator_bundle = _select_locator_bundle_for_check(
                    check_code=check_definition.check_code,
                    state_signature=check_state_signature,
                    default_state_signature=default_state_signature,
                    elements=normalized_elements,
                )
                module_plan_draft = build_module_plan(
                    check_code=check_definition.check_code,
                    page_context=page_context,
                    state_signature=check_state_signature,
                    locator_bundle={"candidates": locator_bundle.candidates},
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
                page_check.input_schema = {
                    **(check_definition.input_schema or {}),
                    "state_signature": check_state_signature,
                }
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

            navigation_alias_drafts = build_navigation_aliases(
                page_title=page.page_title,
                route_path=_normalize_route_path(page.route_path),
                menu_topology=_build_navigation_menu_topology(
                    page_id=page.id,
                    menus=menus,
                    menus_by_id=menus_by_id,
                ),
            )
            await self._replace_navigation_aliases(
                system_id=system.id,
                page_asset_id=page_asset.id,
                snapshot_id=snapshot.id,
                drafts=navigation_alias_drafts,
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
                enabled_alias_ids=[str(alias_id) for alias_id in alias_ids_to_enable],
                paused_published_job_ids=[str(job_id) for job_id in published_job_ids_to_pause],
                resumed_published_job_ids=[str(job_id) for job_id in published_job_ids_to_resume],
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

    async def _find_page_check(
        self,
        *,
        page_asset_id: UUID,
        check_code: str,
    ) -> PageCheck | None:
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
            if (alias.asset_key, alias.check_alias) in check_target_set and _is_system_disabled_alias(alias):
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
        paused_jobs = await self._exec_all(
            select(PublishedJob)
            .where(PublishedJob.page_check_id.in_(page_check_ids))
            .where(PublishedJob.state == PublishedJobState.PAUSED)
            .order_by(PublishedJob.id)
        )
        return [job for job in paused_jobs if _is_system_paused_job(job)]

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

    async def _replace_navigation_aliases(
        self,
        *,
        system_id: UUID,
        page_asset_id: UUID,
        snapshot_id: UUID,
        drafts: list[NavigationAliasDraft],
    ) -> None:
        existing_aliases = await self._exec_all(
            select(PageNavigationAlias)
            .where(PageNavigationAlias.page_asset_id == page_asset_id)
            .where(PageNavigationAlias.is_active.is_(True))
            .order_by(PageNavigationAlias.id)
        )
        disabled_at = _utcnow()
        for alias in existing_aliases:
            alias.is_active = False
            alias.disabled_reason = "recompiled"
            alias.disabled_at = disabled_at
            alias.disabled_by_snapshot_id = snapshot_id

        for draft in drafts:
            self.session.add(
                PageNavigationAlias(
                    system_id=system_id,
                    page_asset_id=page_asset_id,
                    alias_type=draft.alias_type,
                    alias_text=draft.alias_text,
                    leaf_text=draft.leaf_text,
                    display_chain=draft.display_chain,
                    chain_complete=draft.chain_complete,
                    source="asset_compiler",
                    is_active=True,
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


def _build_navigation_menu_topology(
    *,
    page_id: UUID,
    menus: list[MenuNode],
    menus_by_id: dict[UUID, MenuNode],
) -> list[MenuNode]:
    topology: list[MenuNode] = []
    seen_ids: set[UUID] = set()
    page_menus = [menu for menu in menus if menu.page_id == page_id]
    for menu in page_menus:
        _append_menu_with_ancestors(
            menu=menu,
            menus_by_id=menus_by_id,
            topology=topology,
            seen_ids=seen_ids,
        )
    return topology


def _append_menu_with_ancestors(
    *,
    menu: MenuNode,
    menus_by_id: dict[UUID, MenuNode],
    topology: list[MenuNode],
    seen_ids: set[UUID],
) -> None:
    lineage: list[MenuNode] = []
    visited: set[UUID] = set()
    current: MenuNode | None = menu
    while current is not None and current.id not in visited:
        lineage.append(current)
        visited.add(current.id)
        if current.parent_id is None:
            break
        current = menus_by_id.get(current.parent_id)
    for node in reversed(lineage):
        if node.id in seen_ids:
            continue
        seen_ids.add(node.id)
        topology.append(node)


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


def _build_default_state_signature(route_path: str) -> str:
    route_segments = [segment for segment in route_path.strip("/").split("/") if segment]
    page_key = route_segments[-1] if route_segments else "page"
    return f"{page_key}:default"


def _build_normalized_element(
    *,
    element: PageElement,
    default_state_signature: str,
) -> dict[str, object]:
    raw_candidates = list(element.locator_candidates or [])
    if not raw_candidates and element.playwright_locator:
        raw_candidates = [
            {
                "strategy_type": _infer_strategy_type(element.playwright_locator),
                "selector": element.playwright_locator,
            }
        ]
    state_signature = _normalize_text(element.state_signature) or default_state_signature
    state_context = dict(element.state_context or {})
    locator_bundle = build_locator_bundle(
        locator_candidates=raw_candidates,
        state_context=state_context,
    )
    return {
        "element_type": _normalize_text(element.element_type),
        "element_role": _normalize_text(element.element_role),
        "element_text": _normalize_text(element.element_text),
        "attributes": element.attributes or {},
        "playwright_locator": _normalize_text(element.playwright_locator),
        "usage_description": _normalize_text(element.usage_description),
        "state_signature": state_signature,
        "state_context": state_context,
        "locator_candidates": raw_candidates,
        "materialized_by": _normalize_text(element.materialized_by),
        "navigation_diagnostics": (
            dict(element.navigation_diagnostics)
            if isinstance(element.navigation_diagnostics, dict)
            else {}
        ),
        "locator_bundle": {"candidates": locator_bundle.candidates},
    }


def _collect_representative_states(
    elements: list[dict[str, object]],
) -> list[dict[str, object]]:
    states: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for element in elements:
        state_signature = _normalize_text(element.get("state_signature"))
        state_context = element.get("state_context")
        context = state_context if isinstance(state_context, dict) else {}
        entry_type = _normalize_text(context.get("entry_type"))
        if not state_signature or not entry_type:
            continue
        signature = (state_signature, entry_type)
        if signature in seen:
            continue
        seen.add(signature)
        states.append({"state_signature": state_signature, "entry_type": entry_type})
    return states


def _select_locator_bundle_for_check(
    *,
    check_code: str,
    state_signature: str,
    default_state_signature: str,
    elements: list[dict[str, object]],
) -> LocatorBundle:
    expected_element_type = _expected_element_type_for_check(check_code)
    preferred_states = [state_signature]
    if state_signature != default_state_signature:
        preferred_states.append(default_state_signature)

    for candidate_state in preferred_states:
        matched = _find_element_bundle(
            elements=elements,
            element_type=expected_element_type,
            state_signature=candidate_state,
        )
        if matched is not None:
            return matched

    fallback = _find_element_bundle(
        elements=elements,
        element_type=expected_element_type,
        state_signature="",
    )
    if fallback is not None:
        return fallback
    return LocatorBundle(candidates=[])


def _find_element_bundle(
    *,
    elements: list[dict[str, object]],
    element_type: str | None,
    state_signature: str,
) -> LocatorBundle | None:
    for element in elements:
        current_state = _normalize_text(element.get("state_signature"))
        if state_signature and current_state != state_signature:
            continue
        current_type = _normalize_text(element.get("element_type"))
        if element_type and current_type != element_type:
            continue
        locator_bundle = element.get("locator_bundle")
        if not isinstance(locator_bundle, dict):
            continue
        candidates = locator_bundle.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            continue
        return LocatorBundle(candidates=[_normalize_locator_candidate(row) for row in candidates])
    return None


def _normalize_locator_candidate(candidate: object) -> dict[str, object]:
    payload = candidate if isinstance(candidate, dict) else {}
    return {
        "strategy_type": _normalize_text(payload.get("strategy_type")),
        "selector": _normalize_text(payload.get("selector")),
        "context_constraints": payload.get("context_constraints") if isinstance(payload.get("context_constraints"), dict) else {},
        "stability_score": _normalize_float(payload.get("stability_score")),
        "specificity_score": _normalize_float(payload.get("specificity_score")),
        "observed_success_count": _normalize_int(payload.get("observed_success_count")),
        "fallback_rank": _normalize_int(payload.get("fallback_rank")),
    }


def _expected_element_type_for_check(check_code: str) -> str | None:
    if check_code in {"table_render", "tab_switch_render"}:
        return "table"
    if check_code == "open_create_modal":
        return "button"
    if check_code == "open_create_modal_state":
        return "dialog"
    return None


def _infer_strategy_type(playwright_locator: str) -> str:
    locator = _normalize_text(playwright_locator).lower()
    if "get_by_role" in locator or locator.startswith("role="):
        return "semantic"
    if "get_by_label" in locator or locator.startswith("label="):
        return "label"
    if "testid" in locator or "data-testid" in locator:
        return "testid"
    if "get_by_text" in locator or locator.startswith("text="):
        return "text_anchor"
    return "css"


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


def _normalize_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    return 0


def _normalize_float(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0


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


def _is_system_disabled_alias(alias: IntentAlias) -> bool:
    if alias.disabled_by_snapshot_id is None:
        return False
    reason = (alias.disabled_reason or "").strip().lower()
    if not reason:
        return False
    return reason.startswith("retired_") or reason.startswith("asset_retired") or "retired" in reason


def _is_system_paused_job(job: PublishedJob) -> bool:
    reason = (job.pause_reason or "").strip().lower()
    if "retired" not in reason:
        return False
    return any(
        (
            job.paused_by_snapshot_id is not None,
            job.paused_by_asset_id is not None,
            job.paused_by_page_check_id is not None,
        )
    )
