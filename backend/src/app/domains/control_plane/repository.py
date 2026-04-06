from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from sqlalchemy import case
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, desc, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.domains.control_plane.runtime_policies import (
    UpsertSystemAuthPolicy,
    UpsertSystemCrawlPolicy,
    resolve_runtime_policy_state,
)
from app.domains.control_plane.recommendation import CheckCandidateStats
from app.domains.control_plane.schemas import (
    CheckRequestStatus,
    CreateCheckRequest,
    PageAssetCheckItem,
    PageAssetChecksList,
)
from app.infrastructure.db.models.assets import IntentAlias, PageAsset, PageCheck, PageNavigationAlias
from app.infrastructure.db.models.crawl import CrawlSnapshot, Page
from app.domains.runner_service.result_views import (
    ArtifactItem,
    CheckResultView,
    ExecutionSummary,
)
from app.infrastructure.db.models.execution import (
    ExecutionArtifact,
    ExecutionPlan,
    ExecutionRequest,
    ExecutionRun,
)
from app.infrastructure.db.models.jobs import QueuedJob
from app.infrastructure.db.models.runtime_policies import SystemAuthPolicy, SystemCrawlPolicy
from app.infrastructure.db.models.systems import System
from app.shared.enums import AssetLifecycleStatus, AssetStatus, QueuedJobStatus, RuntimePolicyState


@dataclass(frozen=True)
class PageCheckRunTarget:
    system: System
    page_asset: PageAsset
    page_check: PageCheck


@dataclass(frozen=True)
class CheckResolution:
    system: System | None
    page_asset: PageAsset | None
    page_check: PageCheck | None
    miss_reason: str | None


@dataclass(frozen=True)
class PageCheckLookup:
    system: System
    page_asset: PageAsset
    page_check: PageCheck


@dataclass(frozen=True)
class RetiredResolutionTarget:
    page_asset: PageAsset
    page_check: PageCheck | None = None


class ControlPlaneRepository(Protocol):
    async def get_system_by_id(self, *, system_id: UUID) -> System | None: ...

    async def get_system_auth_policy(self, *, system_id: UUID) -> SystemAuthPolicy | None: ...

    async def upsert_system_auth_policy(
        self,
        *,
        system_id: UUID,
        payload: UpsertSystemAuthPolicy,
    ) -> SystemAuthPolicy: ...

    async def get_system_crawl_policy(self, *, system_id: UUID) -> SystemCrawlPolicy | None: ...

    async def upsert_system_crawl_policy(
        self,
        *,
        system_id: UUID,
        payload: UpsertSystemCrawlPolicy,
    ) -> SystemCrawlPolicy: ...

    async def list_active_auth_policies(self) -> list[SystemAuthPolicy]: ...

    async def list_active_crawl_policies(self) -> list[SystemCrawlPolicy]: ...

    async def get_snapshot_by_id(
        self,
        *,
        snapshot_id: UUID,
    ) -> CrawlSnapshot | None: ...

    async def resolve_system(self, *, system_hint: str) -> System | None: ...

    async def resolve_page_asset_and_check(
        self,
        *,
        system_hint: str,
        page_hint: str | None,
        check_goal: str,
    ) -> CheckResolution: ...

    async def list_check_candidates(
        self,
        *,
        system_hint: str,
        page_hint: str | None,
    ) -> list[CheckCandidateStats]: ...

    async def create_execution_request(
        self,
        *,
        payload: CreateCheckRequest,
    ) -> ExecutionRequest: ...

    async def create_execution_plan(
        self,
        *,
        execution_request_id: UUID,
        resolved_system_id: UUID | None,
        resolved_page_asset_id: UUID | None,
        resolved_page_check_id: UUID | None,
        execution_track: str,
        auth_policy: str,
        module_plan_id: UUID | None,
    ) -> ExecutionPlan: ...

    async def get_check_request_status(
        self,
        *,
        request_id: UUID,
    ) -> CheckRequestStatus | None: ...

    async def get_check_request_result_view(
        self,
        *,
        request_id: UUID,
    ) -> CheckResultView | None: ...

    async def get_page_check_run_target(
        self,
        *,
        page_check_id: UUID,
    ) -> PageCheckRunTarget | None: ...

    async def get_page_check_lookup(
        self,
        *,
        page_check_id: UUID,
    ) -> PageCheckLookup | None: ...

    async def resolve_retired_page_asset_or_check(
        self,
        *,
        system_hint: str,
        system_id: UUID | None,
        page_hint: str | None,
        check_goal: str,
    ) -> RetiredResolutionTarget | None: ...

    async def get_page_asset_checks(
        self,
        *,
        page_asset_id: UUID,
    ) -> PageAssetChecksList | None: ...

    async def get_execution_plan(
        self,
        *,
        execution_plan_id: UUID,
    ) -> ExecutionPlan | None: ...

    async def get_execution_request(
        self,
        *,
        execution_request_id: UUID,
    ) -> ExecutionRequest | None: ...

    async def get_page_asset(
        self,
        *,
        page_asset_id: UUID,
    ) -> PageAsset | None: ...

    async def get_page(
        self,
        *,
        page_id: UUID,
    ) -> Page | None: ...

    async def get_latest_execution_run(
        self,
        *,
        execution_plan_id: UUID,
    ) -> ExecutionRun | None: ...

    async def get_execution_run(
        self,
        *,
        execution_run_id: UUID,
    ) -> ExecutionRun | None: ...

    async def upsert_intent_alias(
        self,
        *,
        system_alias: str,
        page_alias: str | None,
        check_alias: str,
        route_hint: str | None,
        asset_key: str,
        source: str,
        confidence: float = 1.0,
    ) -> IntentAlias: ...

    async def disable_aliases_from_compiler_decisions(
        self,
        *,
        alias_ids: list[UUID],
        snapshot_id: UUID,
        reason: str,
    ) -> int: ...

    async def enable_aliases_from_compiler_decisions(
        self,
        *,
        alias_ids: list[UUID],
    ) -> int: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class SqlControlPlaneRepository:
    def __init__(self, session: Session | AsyncSession) -> None:
        self.session = session

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

    async def _get(self, model, identifier):
        if isinstance(self.session, AsyncSession):
            return await self.session.get(model, identifier)
        return self.session.get(model, identifier)

    async def _flush(self) -> None:
        if isinstance(self.session, AsyncSession):
            await self.session.flush()
            return
        self.session.flush()

    async def _refresh(self, model) -> None:
        if isinstance(self.session, AsyncSession):
            await self.session.refresh(model)
            return
        self.session.refresh(model)

    async def get_system_by_id(self, *, system_id: UUID) -> System | None:
        return await self._get(System, system_id)

    async def get_system_auth_policy(self, *, system_id: UUID) -> SystemAuthPolicy | None:
        statement = select(SystemAuthPolicy).where(SystemAuthPolicy.system_id == system_id)
        return await self._exec_first(statement)

    async def upsert_system_auth_policy(
        self,
        *,
        system_id: UUID,
        payload: UpsertSystemAuthPolicy,
    ) -> SystemAuthPolicy:
        policy = await self.get_system_auth_policy(system_id=system_id)
        next_state = resolve_runtime_policy_state(enabled=payload.enabled)
        created_new_row = policy is None
        if policy is None:
            policy = SystemAuthPolicy(
                system_id=system_id,
                enabled=payload.enabled,
                state=next_state,
                schedule_expr=payload.schedule_expr,
                auth_mode=payload.auth_mode,
                captcha_provider=payload.captcha_provider,
            )
            self.session.add(policy)
        else:
            policy.enabled = payload.enabled
            policy.state = next_state
            policy.schedule_expr = payload.schedule_expr
            policy.auth_mode = payload.auth_mode
            policy.captcha_provider = payload.captcha_provider
            self.session.add(policy)

        try:
            await self._flush()
        except IntegrityError as exc:
            if not created_new_row or not _is_unique_system_id_violation(
                exc=exc,
                table_name="system_auth_policies",
            ):
                raise
            await self.rollback()
            policy = await self.get_system_auth_policy(system_id=system_id)
            if policy is None:
                raise
            policy.enabled = payload.enabled
            policy.state = next_state
            policy.schedule_expr = payload.schedule_expr
            policy.auth_mode = payload.auth_mode
            policy.captcha_provider = payload.captcha_provider
            self.session.add(policy)
            await self._flush()

        await self._refresh(policy)
        return policy

    async def get_system_crawl_policy(self, *, system_id: UUID) -> SystemCrawlPolicy | None:
        statement = select(SystemCrawlPolicy).where(SystemCrawlPolicy.system_id == system_id)
        return await self._exec_first(statement)

    async def upsert_system_crawl_policy(
        self,
        *,
        system_id: UUID,
        payload: UpsertSystemCrawlPolicy,
    ) -> SystemCrawlPolicy:
        policy = await self.get_system_crawl_policy(system_id=system_id)
        next_state = resolve_runtime_policy_state(enabled=payload.enabled)
        created_new_row = policy is None
        if policy is None:
            policy = SystemCrawlPolicy(
                system_id=system_id,
                enabled=payload.enabled,
                state=next_state,
                schedule_expr=payload.schedule_expr,
                crawl_scope=payload.crawl_scope,
            )
            self.session.add(policy)
        else:
            policy.enabled = payload.enabled
            policy.state = next_state
            policy.schedule_expr = payload.schedule_expr
            policy.crawl_scope = payload.crawl_scope
            self.session.add(policy)

        try:
            await self._flush()
        except IntegrityError as exc:
            if not created_new_row or not _is_unique_system_id_violation(
                exc=exc,
                table_name="system_crawl_policies",
            ):
                raise
            await self.rollback()
            policy = await self.get_system_crawl_policy(system_id=system_id)
            if policy is None:
                raise
            policy.enabled = payload.enabled
            policy.state = next_state
            policy.schedule_expr = payload.schedule_expr
            policy.crawl_scope = payload.crawl_scope
            self.session.add(policy)
            await self._flush()

        await self._refresh(policy)
        return policy

    async def list_active_auth_policies(self) -> list[SystemAuthPolicy]:
        statement = (
            select(SystemAuthPolicy)
            .where(SystemAuthPolicy.enabled.is_(True))
            .where(SystemAuthPolicy.state == RuntimePolicyState.ACTIVE.value)
            .order_by(SystemAuthPolicy.system_id)
        )
        return await self._exec_all(statement)

    async def list_active_crawl_policies(self) -> list[SystemCrawlPolicy]:
        statement = (
            select(SystemCrawlPolicy)
            .where(SystemCrawlPolicy.enabled.is_(True))
            .where(SystemCrawlPolicy.state == RuntimePolicyState.ACTIVE.value)
            .order_by(SystemCrawlPolicy.system_id)
        )
        return await self._exec_all(statement)

    async def get_snapshot_by_id(
        self,
        *,
        snapshot_id: UUID,
    ) -> CrawlSnapshot | None:
        return await self._get(CrawlSnapshot, snapshot_id)

    async def resolve_system(self, *, system_hint: str) -> System | None:
        normalized_hint = system_hint.strip().lower()
        statement = select(System).where(
            (func.lower(System.code) == normalized_hint)
            | (func.lower(System.name) == normalized_hint)
        )
        return await self._exec_first(statement)

    async def resolve_page_asset_and_check(
        self,
        *,
        system_hint: str,
        page_hint: str | None,
        check_goal: str,
    ) -> CheckResolution:
        normalized_system_hint = system_hint.strip().lower()
        normalized_goal = check_goal.strip().lower()
        system = await self.resolve_system(system_hint=system_hint)
        if system is None:
            return CheckResolution(
                system=None,
                page_asset=None,
                page_check=None,
                miss_reason="system_not_found",
            )

        if page_hint is None:
            return CheckResolution(
                system=system,
                page_asset=None,
                page_check=None,
                miss_reason="page_or_menu_not_resolved",
            )

        normalized_page_hint = page_hint.strip().lower()
        navigation_matches = await self._list_navigation_alias_resolution_matches(
            system_id=system.id,
            normalized_page_hint=normalized_page_hint,
            normalized_goal=normalized_goal,
        )
        if len(navigation_matches) > 1:
            return CheckResolution(
                system=system,
                page_asset=None,
                page_check=None,
                miss_reason="ambiguous_page_alias",
            )
        if len(navigation_matches) == 1:
            page_asset, page_check, _ = navigation_matches[0]
            return CheckResolution(
                system=system,
                page_asset=page_asset,
                page_check=page_check,
                miss_reason=None,
            )

        asset_statement = (
            select(PageAsset)
            .join(IntentAlias, IntentAlias.asset_key == PageAsset.asset_key)
            .where(PageAsset.status == AssetStatus.SAFE)
            .where(PageAsset.system_id == system.id)
            .where(PageAsset.lifecycle_status == AssetLifecycleStatus.ACTIVE)
            .where(IntentAlias.is_active.is_(True))
            .where(func.lower(IntentAlias.system_alias) == normalized_system_hint)
            .where(func.lower(IntentAlias.check_alias) == normalized_goal)
            .where(
                (func.lower(IntentAlias.page_alias) == normalized_page_hint)
                | (func.lower(IntentAlias.route_hint) == normalized_page_hint)
            )
            .order_by(IntentAlias.confidence.desc(), PageAsset.asset_version.desc())
        )
        page_asset = await self._exec_first(asset_statement)
        if page_asset is not None:
            check_statement = (
                select(PageCheck)
                .where(PageCheck.page_asset_id == page_asset.id)
                .where(PageCheck.lifecycle_status == AssetLifecycleStatus.ACTIVE)
                .where(
                    (func.lower(PageCheck.goal) == normalized_goal)
                    | (func.lower(PageCheck.check_code) == normalized_goal)
                )
                .order_by(PageCheck.id)
            )
            page_check = await self._exec_first(check_statement)
            if page_check is None:
                return CheckResolution(
                    system=system,
                    page_asset=page_asset,
                    page_check=None,
                    miss_reason="element_asset_missing",
                )
            return CheckResolution(
                system=system,
                page_asset=page_asset,
                page_check=page_check,
                miss_reason=None,
            )

        asset_statement = (
            select(PageAsset)
            .join(Page, Page.id == PageAsset.page_id)
            .where(PageAsset.system_id == system.id)
            .where(PageAsset.status == AssetStatus.SAFE)
            .where(PageAsset.lifecycle_status == AssetLifecycleStatus.ACTIVE)
            .where(
                (func.lower(Page.page_title) == normalized_page_hint)
                | (func.lower(Page.route_path) == normalized_page_hint)
                | (func.lower(PageAsset.asset_key) == normalized_page_hint)
            )
            .order_by(PageAsset.asset_version.desc(), PageAsset.id)
        )
        page_asset = await self._exec_first(asset_statement)
        if page_asset is None:
            return CheckResolution(
                system=system,
                page_asset=None,
                page_check=None,
                miss_reason="page_or_menu_not_resolved",
            )

        check_statement = (
            select(PageCheck)
            .where(PageCheck.page_asset_id == page_asset.id)
            .where(PageCheck.lifecycle_status == AssetLifecycleStatus.ACTIVE)
            .where(
                (func.lower(PageCheck.goal) == normalized_goal)
                | (func.lower(PageCheck.check_code) == normalized_goal)
            )
            .order_by(PageCheck.id)
        )
        page_check = await self._exec_first(check_statement)
        if page_check is None:
            return CheckResolution(
                system=system,
                page_asset=page_asset,
                page_check=None,
                miss_reason="element_asset_missing",
            )
        return CheckResolution(
            system=system,
            page_asset=page_asset,
            page_check=page_check,
            miss_reason=None,
        )

    async def list_check_candidates(
        self,
        *,
        system_hint: str,
        page_hint: str | None,
    ) -> list[CheckCandidateStats]:
        system = await self.resolve_system(system_hint=system_hint)
        if system is None or page_hint is None:
            return []

        normalized_system_hint = system_hint.strip().lower()
        normalized_page_hint = page_hint.strip().lower()

        alias_confidence_subquery = (
            select(
                IntentAlias.asset_key.label("asset_key"),
                func.max(IntentAlias.confidence).label("alias_confidence"),
            )
            .where(IntentAlias.is_active.is_(True))
            .where(func.lower(IntentAlias.system_alias) == normalized_system_hint)
            .where(
                (func.lower(IntentAlias.page_alias) == normalized_page_hint)
                | (func.lower(IntentAlias.route_hint) == normalized_page_hint)
            )
            .group_by(IntentAlias.asset_key)
            .subquery()
        )
        navigation_alias_ranked_subquery = (
            select(
                PageNavigationAlias.page_asset_id.label("page_asset_id"),
                PageNavigationAlias.leaf_text.label("leaf_text"),
                PageNavigationAlias.display_chain.label("display_chain"),
                PageNavigationAlias.chain_complete.label("chain_complete"),
                func.row_number()
                .over(
                    partition_by=PageNavigationAlias.page_asset_id,
                    order_by=(
                        PageNavigationAlias.chain_complete.desc(),
                        PageNavigationAlias.id,
                    ),
                )
                .label("alias_rank"),
            )
            .where(PageNavigationAlias.is_active.is_(True))
            .where(func.lower(PageNavigationAlias.alias_text) == normalized_page_hint)
            .subquery()
        )
        navigation_alias_subquery = (
            select(
                navigation_alias_ranked_subquery.c.page_asset_id,
                navigation_alias_ranked_subquery.c.leaf_text,
                navigation_alias_ranked_subquery.c.display_chain,
                navigation_alias_ranked_subquery.c.chain_complete,
            )
            .where(navigation_alias_ranked_subquery.c.alias_rank == 1)
            .subquery()
        )

        sample_count = func.count(ExecutionRun.id).label("sample_count")
        last_run_at = func.max(ExecutionRun.created_at).label("last_run_at")
        alias_confidence = case(
            (alias_confidence_subquery.c.alias_confidence.is_not(None), alias_confidence_subquery.c.alias_confidence),
            (navigation_alias_subquery.c.page_asset_id.is_not(None), 1.0),
            else_=0.0,
        ).label("alias_confidence")

        statement = (
            select(
                PageCheck.id,
                PageCheck.page_asset_id,
                PageAsset.asset_key,
                PageCheck.check_code,
                PageCheck.goal,
                navigation_alias_subquery.c.leaf_text,
                navigation_alias_subquery.c.display_chain,
                func.coalesce(navigation_alias_subquery.c.chain_complete, False).label("chain_complete"),
                alias_confidence,
                PageCheck.success_rate,
                sample_count,
                last_run_at,
            )
            .join(PageAsset, PageAsset.id == PageCheck.page_asset_id)
            .join(Page, Page.id == PageAsset.page_id)
            .outerjoin(
                alias_confidence_subquery,
                alias_confidence_subquery.c.asset_key == PageAsset.asset_key,
            )
            .outerjoin(
                navigation_alias_subquery,
                navigation_alias_subquery.c.page_asset_id == PageAsset.id,
            )
            .outerjoin(ExecutionPlan, ExecutionPlan.resolved_page_check_id == PageCheck.id)
            .outerjoin(ExecutionRun, ExecutionRun.execution_plan_id == ExecutionPlan.id)
            .where(PageAsset.system_id == system.id)
            .where(PageAsset.status == AssetStatus.SAFE)
            .where(PageAsset.lifecycle_status == AssetLifecycleStatus.ACTIVE)
            .where(PageCheck.lifecycle_status == AssetLifecycleStatus.ACTIVE)
            .where(
                (navigation_alias_subquery.c.page_asset_id.is_not(None))
                | (alias_confidence_subquery.c.asset_key.is_not(None))
                | (func.lower(Page.page_title) == normalized_page_hint)
                | (func.lower(Page.route_path) == normalized_page_hint)
                | (func.lower(PageAsset.asset_key) == normalized_page_hint)
            )
            .group_by(
                PageCheck.id,
                PageCheck.page_asset_id,
                PageAsset.asset_key,
                PageAsset.asset_version,
                PageCheck.check_code,
                PageCheck.goal,
                navigation_alias_subquery.c.page_asset_id,
                navigation_alias_subquery.c.leaf_text,
                navigation_alias_subquery.c.display_chain,
                navigation_alias_subquery.c.chain_complete,
                alias_confidence_subquery.c.alias_confidence,
                PageCheck.success_rate,
            )
            .order_by(alias_confidence.desc(), PageAsset.asset_version.desc(), PageCheck.id)
        )
        rows = await self._exec_all(statement)
        candidates: list[CheckCandidateStats] = []
        for row in rows:
            candidates.append(
                CheckCandidateStats(
                    page_asset_id=row.page_asset_id,
                    page_check_id=row.id,
                    asset_key=row.asset_key,
                    check_code=row.check_code,
                    goal=row.goal,
                    leaf_text=row.leaf_text,
                    display_chain=row.display_chain,
                    chain_complete=bool(row.chain_complete),
                    alias_confidence=row.alias_confidence or 0.0,
                    success_rate=row.success_rate,
                    last_run_at=row.last_run_at,
                    sample_count=row.sample_count or 0,
                )
            )
        return candidates

    async def _list_navigation_alias_resolution_matches(
        self,
        *,
        system_id: UUID,
        normalized_page_hint: str,
        normalized_goal: str,
    ) -> list[tuple[PageAsset, PageCheck, PageNavigationAlias]]:
        statement = (
            select(PageAsset, PageCheck, PageNavigationAlias)
            .join(PageCheck, PageCheck.page_asset_id == PageAsset.id)
            .join(PageNavigationAlias, PageNavigationAlias.page_asset_id == PageAsset.id)
            .where(PageAsset.system_id == system_id)
            .where(PageAsset.status == AssetStatus.SAFE)
            .where(PageAsset.lifecycle_status == AssetLifecycleStatus.ACTIVE)
            .where(PageCheck.lifecycle_status == AssetLifecycleStatus.ACTIVE)
            .where(PageNavigationAlias.is_active.is_(True))
            .where(func.lower(PageNavigationAlias.alias_text) == normalized_page_hint)
            .where(
                (func.lower(PageCheck.goal) == normalized_goal)
                | (func.lower(PageCheck.check_code) == normalized_goal)
            )
            .order_by(
                PageNavigationAlias.chain_complete.desc(),
                PageAsset.asset_version.desc(),
                PageCheck.id,
                PageNavigationAlias.id,
            )
        )
        rows = await self._exec_all(statement)
        deduped: list[tuple[PageAsset, PageCheck, PageNavigationAlias]] = []
        seen_page_check_ids: set[UUID] = set()
        for page_asset, page_check, navigation_alias in rows:
            if page_check.id in seen_page_check_ids:
                continue
            seen_page_check_ids.add(page_check.id)
            deduped.append((page_asset, page_check, navigation_alias))
        return deduped

    async def get_execution_plan(
        self,
        *,
        execution_plan_id: UUID,
    ) -> ExecutionPlan | None:
        return await self._get(ExecutionPlan, execution_plan_id)

    async def get_execution_request(
        self,
        *,
        execution_request_id: UUID,
    ) -> ExecutionRequest | None:
        return await self._get(ExecutionRequest, execution_request_id)

    async def get_page_asset(
        self,
        *,
        page_asset_id: UUID,
    ) -> PageAsset | None:
        return await self._get(PageAsset, page_asset_id)

    async def get_page(
        self,
        *,
        page_id: UUID,
    ) -> Page | None:
        return await self._get(Page, page_id)

    async def get_latest_execution_run(
        self,
        *,
        execution_plan_id: UUID,
    ) -> ExecutionRun | None:
        statement = (
            select(ExecutionRun)
            .where(ExecutionRun.execution_plan_id == execution_plan_id)
            .order_by(ExecutionRun.created_at.desc(), ExecutionRun.id.desc())
        )
        return await self._exec_first(statement)

    async def get_execution_run(
        self,
        *,
        execution_run_id: UUID,
    ) -> ExecutionRun | None:
        return await self._get(ExecutionRun, execution_run_id)

    async def upsert_intent_alias(
        self,
        *,
        system_alias: str,
        page_alias: str | None,
        check_alias: str,
        route_hint: str | None,
        asset_key: str,
        source: str,
        confidence: float = 1.0,
    ) -> IntentAlias:
        statement = (
            select(IntentAlias)
            .where(IntentAlias.system_alias == system_alias)
            .where(IntentAlias.page_alias == page_alias)
            .where(IntentAlias.check_alias == check_alias)
            .where(IntentAlias.asset_key == asset_key)
        )
        alias = await self._exec_first(statement)
        if alias is None:
            alias = IntentAlias(
                system_alias=system_alias,
                page_alias=page_alias,
                check_alias=check_alias,
                route_hint=route_hint,
                asset_key=asset_key,
                confidence=confidence,
                source=source,
            )
            self.session.add(alias)
            await self._flush()
            await self._refresh(alias)
            return alias

        alias.route_hint = route_hint
        alias.confidence = confidence
        alias.source = source
        self.session.add(alias)
        await self._flush()
        await self._refresh(alias)
        return alias

    async def resolve_retired_page_asset_or_check(
        self,
        *,
        system_hint: str,
        system_id: UUID | None,
        page_hint: str | None,
        check_goal: str,
    ) -> RetiredResolutionTarget | None:
        if page_hint is None:
            return None

        normalized_system_hint = system_hint.strip().lower()
        normalized_goal = check_goal.strip().lower()
        normalized_page_hint = page_hint.strip().lower()

        alias_statement = (
            select(PageAsset)
            .join(IntentAlias, IntentAlias.asset_key == PageAsset.asset_key)
            .where(PageAsset.status == AssetStatus.SAFE)
            .where(func.lower(IntentAlias.system_alias) == normalized_system_hint)
            .where(func.lower(IntentAlias.check_alias) == normalized_goal)
            .where(
                (func.lower(IntentAlias.page_alias) == normalized_page_hint)
                | (func.lower(IntentAlias.route_hint) == normalized_page_hint)
            )
            .order_by(IntentAlias.confidence.desc(), PageAsset.asset_version.desc())
        )
        if system_id is not None:
            alias_statement = alias_statement.where(PageAsset.system_id == system_id)

        alias_asset = await self._exec_first(alias_statement)
        if alias_asset is not None:
            retired_target = await self._build_retired_resolution_target(
                page_asset=alias_asset,
                normalized_goal=normalized_goal,
            )
            if retired_target is not None:
                return retired_target

        if system_id is None:
            return None

        page_statement = (
            select(PageAsset)
            .join(Page, Page.id == PageAsset.page_id)
            .where(PageAsset.system_id == system_id)
            .where(PageAsset.status == AssetStatus.SAFE)
            .where(
                (func.lower(Page.page_title) == normalized_page_hint)
                | (func.lower(Page.route_path) == normalized_page_hint)
                | (func.lower(PageAsset.asset_key) == normalized_page_hint)
            )
            .order_by(PageAsset.asset_version.desc(), PageAsset.id)
        )
        page_asset = await self._exec_first(page_statement)
        if page_asset is None:
            return None
        return await self._build_retired_resolution_target(
            page_asset=page_asset,
            normalized_goal=normalized_goal,
        )

    async def _build_retired_resolution_target(
        self,
        *,
        page_asset: PageAsset,
        normalized_goal: str,
    ) -> RetiredResolutionTarget | None:
        if page_asset.lifecycle_status != AssetLifecycleStatus.ACTIVE:
            return RetiredResolutionTarget(page_asset=page_asset)

        retired_check = await self._exec_first(
            select(PageCheck)
            .where(PageCheck.page_asset_id == page_asset.id)
            .where(
                (func.lower(PageCheck.goal) == normalized_goal)
                | (func.lower(PageCheck.check_code) == normalized_goal)
            )
            .where(PageCheck.lifecycle_status != AssetLifecycleStatus.ACTIVE)
            .order_by(PageCheck.id)
        )
        if retired_check is None:
            return None
        return RetiredResolutionTarget(page_asset=page_asset, page_check=retired_check)

    async def create_execution_request(
        self,
        *,
        payload: CreateCheckRequest,
    ) -> ExecutionRequest:
        request = ExecutionRequest(
            request_source=payload.request_source,
            system_hint=payload.system_hint,
            page_hint=payload.page_hint,
            check_goal=payload.check_goal,
            strictness=payload.strictness,
            time_budget_ms=payload.time_budget_ms,
            template_code=payload.template_code,
            template_version=payload.template_version,
            carrier_hint=payload.carrier_hint,
            template_params=payload.template_params,
        )
        self.session.add(request)
        await self._flush()
        return request

    async def create_execution_plan(
        self,
        *,
        execution_request_id: UUID,
        resolved_system_id: UUID | None,
        resolved_page_asset_id: UUID | None,
        resolved_page_check_id: UUID | None,
        execution_track: str,
        auth_policy: str,
        module_plan_id: UUID | None,
    ) -> ExecutionPlan:
        plan = ExecutionPlan(
            execution_request_id=execution_request_id,
            resolved_system_id=resolved_system_id,
            resolved_page_asset_id=resolved_page_asset_id,
            resolved_page_check_id=resolved_page_check_id,
            execution_track=execution_track,
            auth_policy=auth_policy,
            module_plan_id=module_plan_id,
        )
        self.session.add(plan)
        await self._flush()
        return plan

    async def get_check_request_status(
        self,
        *,
        request_id: UUID,
    ) -> CheckRequestStatus | None:
        if isinstance(self.session, AsyncSession):
            request = await self.session.get(ExecutionRequest, request_id)
        else:
            request = self.session.get(ExecutionRequest, request_id)
        if request is None:
            return None

        statement = select(ExecutionPlan).where(
            ExecutionPlan.execution_request_id == request_id
        )
        plan = await self._exec_first(statement)
        queued_job = await self._find_check_request_queued_job(request_id=request_id)

        return CheckRequestStatus(
            request_id=request.id,
            plan_id=plan.id if plan else None,
            page_check_id=plan.resolved_page_check_id if plan else None,
            execution_track=_normalize_public_execution_track(plan.execution_track) if plan else None,
            auth_policy=plan.auth_policy if plan else None,
            status=queued_job.status if queued_job else "accepted",
        )

    async def get_check_request_result_view(
        self,
        *,
        request_id: UUID,
    ) -> CheckResultView | None:
        request = await self._get(ExecutionRequest, request_id)
        if request is None:
            return None

        plan = await self._exec_first(
            select(ExecutionPlan).where(ExecutionPlan.execution_request_id == request_id)
        )
        queued_job = await self._find_check_request_queued_job(request_id=request_id)
        if queued_job is not None and queued_job.status not in {
            QueuedJobStatus.COMPLETED.value,
            QueuedJobStatus.FAILED.value,
            QueuedJobStatus.RETRYABLE_FAILED.value,
            QueuedJobStatus.SKIPPED.value,
        }:
            return CheckResultView(
                request_id=request.id,
                plan_id=plan.id if plan else None,
                page_check_id=plan.resolved_page_check_id if plan else None,
                execution_track=_normalize_public_execution_track(plan.execution_track) if plan else None,
                execution_summary=None,
                artifacts=[],
                needs_recrawl=False,
                needs_recompile=False,
            )

        artifacts: list[ExecutionArtifact] = []
        execution_summary: ExecutionSummary | None = None
        if plan is not None:
            execution_run = await self._exec_first(
                select(ExecutionRun)
                .where(ExecutionRun.execution_plan_id == plan.id)
                .order_by(ExecutionRun.created_at.desc(), ExecutionRun.id.desc())
            )
            if execution_run is not None:
                artifacts = await self._exec_all(
                    select(ExecutionArtifact)
                    .where(ExecutionArtifact.execution_run_id == execution_run.id)
                    .order_by(ExecutionArtifact.created_at)
                )
                final_url, page_title = _extract_page_context(artifacts)
                execution_summary = ExecutionSummary(
                    execution_run_id=execution_run.id,
                    status=execution_run.status,
                    auth_status=execution_run.auth_status,
                    duration_ms=execution_run.duration_ms,
                    failure_category=execution_run.failure_category,
                    asset_version=execution_run.asset_version,
                    snapshot_version=execution_run.snapshot_version,
                    final_url=final_url,
                    page_title=page_title,
                )

        needs_recrawl = False
        needs_recompile = False
        extracted_recrawl: bool | None = None
        extracted_recompile: bool | None = None
        if artifacts:
            extracted_recrawl, extracted_recompile = _extract_probe_hints(artifacts)
            if extracted_recrawl is not None:
                needs_recrawl = extracted_recrawl
            if extracted_recompile is not None:
                needs_recompile = extracted_recompile

        if (
            extracted_recrawl is None
            and extracted_recompile is None
            and plan is not None
            and execution_summary is not None
            and execution_summary.status == "passed"
            and plan.execution_track == "realtime_probe"
            and plan.resolved_page_asset_id is None
        ):
            needs_recrawl = True
            needs_recompile = True

        return CheckResultView(
            request_id=request.id,
            plan_id=plan.id if plan else None,
            page_check_id=plan.resolved_page_check_id if plan else None,
            execution_track=_normalize_public_execution_track(plan.execution_track) if plan else None,
            execution_summary=execution_summary,
            artifacts=[
                ArtifactItem(
                    id=artifact.id,
                    artifact_kind=artifact.artifact_kind,
                    result_status=_normalize_enum_value(artifact.result_status),
                    artifact_uri=artifact.artifact_uri,
                    payload=artifact.payload,
                    created_at=artifact.created_at,
                )
                for artifact in artifacts
            ],
            needs_recrawl=needs_recrawl,
            needs_recompile=needs_recompile,
        )

    async def _find_check_request_queued_job(self, *, request_id: UUID) -> QueuedJob | None:
        queued_jobs = await self._exec_all(select(QueuedJob))
        return next(
            (
                job
                for job in queued_jobs
                if job.payload.get("execution_request_id") == str(request_id)
            ),
            None,
        )

    async def get_page_check_run_target(
        self,
        *,
        page_check_id: UUID,
    ) -> PageCheckRunTarget | None:
        statement = (
            select(PageCheck, PageAsset, System)
            .join(PageAsset, PageAsset.id == PageCheck.page_asset_id)
            .join(System, System.id == PageAsset.system_id)
            .where(PageCheck.id == page_check_id)
            .where(PageAsset.status == AssetStatus.SAFE)
            .where(PageAsset.lifecycle_status == AssetLifecycleStatus.ACTIVE)
            .where(PageCheck.lifecycle_status == AssetLifecycleStatus.ACTIVE)
        )
        row = await self._exec_first(statement)
        if row is None:
            return None
        page_check, page_asset, system = row
        return PageCheckRunTarget(
            system=system,
            page_asset=page_asset,
            page_check=page_check,
        )

    async def get_page_check_lookup(
        self,
        *,
        page_check_id: UUID,
    ) -> PageCheckLookup | None:
        statement = (
            select(PageCheck, PageAsset, System)
            .join(PageAsset, PageAsset.id == PageCheck.page_asset_id)
            .join(System, System.id == PageAsset.system_id)
            .where(PageCheck.id == page_check_id)
        )
        row = await self._exec_first(statement)
        if row is None:
            return None
        page_check, page_asset, system = row
        return PageCheckLookup(
            system=system,
            page_asset=page_asset,
            page_check=page_check,
        )

    async def get_page_asset_checks(
        self,
        *,
        page_asset_id: UUID,
    ) -> PageAssetChecksList | None:
        page_asset = await self._get(PageAsset, page_asset_id)
        if page_asset is None:
            return None

        statement = (
            select(PageCheck)
            .where(PageCheck.page_asset_id == page_asset_id)
            .order_by(PageCheck.id)
        )
        checks = await self._exec_all(statement)
        return PageAssetChecksList(
            page_asset_id=page_asset.id,
            checks=[
                PageAssetCheckItem(
                    id=check.id,
                    page_asset_id=check.page_asset_id,
                    check_code=check.check_code,
                    goal=check.goal,
                    module_plan_id=check.module_plan_id,
                    status=page_asset.status.value,
                    drift_status=page_asset.drift_status.value,
                    lifecycle_status=check.lifecycle_status.value,
                )
                for check in checks
            ],
        )

    async def disable_aliases_from_compiler_decisions(
        self,
        *,
        alias_ids: list[UUID],
        snapshot_id: UUID,
        reason: str,
    ) -> int:
        if not alias_ids:
            return 0

        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("reason must not be empty")

        statement = (
            select(IntentAlias)
            .where(IntentAlias.id.in_(alias_ids))
            .where(IntentAlias.is_active.is_(True))
            .with_for_update()
            .order_by(IntentAlias.id)
        )
        aliases = await self._exec_all(statement)
        if not aliases:
            return 0

        now = datetime.now(timezone.utc)
        changed = 0
        for alias in aliases:
            alias.is_active = False
            alias.disabled_reason = normalized_reason
            alias.disabled_at = now
            alias.disabled_by_snapshot_id = snapshot_id
            self.session.add(alias)
            changed += 1

        await self._flush()
        return changed

    async def enable_aliases_from_compiler_decisions(
        self,
        *,
        alias_ids: list[UUID],
    ) -> int:
        if not alias_ids:
            return 0

        statement = (
            select(IntentAlias)
            .where(IntentAlias.id.in_(alias_ids))
            .where(IntentAlias.is_active.is_(False))
            .with_for_update()
            .order_by(IntentAlias.id)
        )
        aliases = await self._exec_all(statement)
        if not aliases:
            return 0

        changed = 0
        for alias in aliases:
            alias.is_active = True
            alias.disabled_reason = None
            alias.disabled_at = None
            alias.disabled_by_snapshot_id = None
            self.session.add(alias)
            changed += 1

        await self._flush()
        return changed

    async def commit(self) -> None:
        if isinstance(self.session, AsyncSession):
            await self.session.commit()
        else:
            self.session.commit()

    async def rollback(self) -> None:
        if isinstance(self.session, AsyncSession):
            await self.session.rollback()
        else:
            self.session.rollback()


def _is_unique_system_id_violation(*, exc: IntegrityError, table_name: str) -> bool:
    message = str(exc).lower()
    return "unique" in message and table_name in message and "system_id" in message


def _normalize_public_execution_track(track: str | None) -> str | None:
    if track == "realtime":
        return "realtime_probe"
    return track


def _extract_page_context(
    artifacts: list[ExecutionArtifact],
) -> tuple[str | None, str | None]:
    for artifact in artifacts:
        if artifact.artifact_kind == "module_execution":
            final_url = _get_payload_text(artifact.payload, "final_url")
            page_title = _get_payload_text(artifact.payload, "page_title")
            if final_url is not None or page_title is not None:
                return final_url, page_title

    for artifact in artifacts:
        final_url = _get_payload_text(artifact.payload, "final_url")
        page_title = _get_payload_text(artifact.payload, "page_title")
        if final_url is not None or page_title is not None:
            return final_url, page_title

    return None, None


def _get_payload_text(payload: dict[str, object] | None, key: str) -> str | None:
    if not payload:
        return None
    value = payload.get(key)
    if isinstance(value, str):
        return value or None
    return None


def _normalize_enum_value(value: object) -> str:
    normalized = getattr(value, "value", value)
    return str(normalized)


def _extract_probe_hints(
    artifacts: list[ExecutionArtifact],
) -> tuple[bool | None, bool | None]:
    needs_recrawl: bool | None = None
    needs_recompile: bool | None = None
    for artifact in artifacts:
        if not artifact.payload:
            continue
        recrawl = _get_payload_bool(artifact.payload, "needs_recrawl")
        recompile = _get_payload_bool(artifact.payload, "needs_recompile")
        if recrawl is not None:
            needs_recrawl = recrawl
        if recompile is not None:
            needs_recompile = recompile
        if needs_recrawl is not None or needs_recompile is not None:
            break
    return needs_recrawl, needs_recompile


def _get_payload_bool(payload: dict[str, object] | None, key: str) -> bool | None:
    if not payload:
        return None
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    return None
