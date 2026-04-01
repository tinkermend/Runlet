from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlmodel import Session, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.domains.control_plane.schemas import (
    CheckRequestStatus,
    CreateCheckRequest,
    PageAssetCheckItem,
    PageAssetChecksList,
)
from app.infrastructure.db.models.assets import IntentAlias, PageAsset, PageCheck
from app.infrastructure.db.models.crawl import CrawlSnapshot, Page
from app.infrastructure.db.models.execution import ExecutionPlan, ExecutionRequest
from app.infrastructure.db.models.jobs import QueuedJob
from app.infrastructure.db.models.systems import System
from app.shared.enums import AssetStatus


@dataclass(frozen=True)
class PageCheckRunTarget:
    system: System
    page_asset: PageAsset
    page_check: PageCheck


class ControlPlaneRepository(Protocol):
    async def get_system_by_id(self, *, system_id: UUID) -> System | None: ...

    async def get_snapshot_by_id(
        self,
        *,
        snapshot_id: UUID,
    ) -> CrawlSnapshot | None: ...

    async def resolve_system(self, *, system_hint: str) -> System | None: ...

    async def resolve_page_asset_and_check(
        self,
        *,
        system_id: UUID | None,
        system_hint: str,
        page_hint: str | None,
        check_goal: str,
    ) -> tuple[PageAsset | None, PageCheck | None]: ...

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

    async def get_page_check_run_target(
        self,
        *,
        page_check_id: UUID,
    ) -> PageCheckRunTarget | None: ...

    async def get_page_asset_checks(
        self,
        *,
        page_asset_id: UUID,
    ) -> PageAssetChecksList | None: ...

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

    async def get_system_by_id(self, *, system_id: UUID) -> System | None:
        return await self._get(System, system_id)

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
        system_id: UUID | None,
        page_hint: str | None,
        check_goal: str,
    ) -> tuple[PageAsset | None, PageCheck | None]:
        normalized_system_hint = system_hint.strip().lower()
        normalized_goal = check_goal.strip().lower()

        if page_hint is not None:
            normalized_page_hint = page_hint.strip().lower()
            asset_statement = (
                select(PageAsset)
                .join(IntentAlias, IntentAlias.asset_key == PageAsset.asset_key)
                .where(PageAsset.status == AssetStatus.READY)
                .where(func.lower(IntentAlias.system_alias) == normalized_system_hint)
                .where(func.lower(IntentAlias.check_alias) == normalized_goal)
                .where(
                    (func.lower(IntentAlias.page_alias) == normalized_page_hint)
                    | (func.lower(IntentAlias.route_hint) == normalized_page_hint)
                )
                .order_by(IntentAlias.confidence.desc(), PageAsset.asset_version.desc())
            )
            if system_id is not None:
                asset_statement = asset_statement.where(PageAsset.system_id == system_id)

            page_asset = await self._exec_first(asset_statement)
            if page_asset is not None:
                check_statement = select(PageCheck).where(PageCheck.page_asset_id == page_asset.id).where(
                    (func.lower(PageCheck.goal) == normalized_goal)
                    | (func.lower(PageCheck.check_code) == normalized_goal)
                ).order_by(PageCheck.id)
                page_check = await self._exec_first(check_statement)
                return page_asset, page_check

        if system_id is None or page_hint is None:
            return None, None

        normalized_page_hint = page_hint.strip().lower()
        asset_statement = (
            select(PageAsset)
            .join(Page, Page.id == PageAsset.page_id)
            .where(PageAsset.system_id == system_id)
            .where(PageAsset.status == AssetStatus.READY)
            .where(
                (func.lower(Page.page_title) == normalized_page_hint)
                | (func.lower(Page.route_path) == normalized_page_hint)
                | (func.lower(PageAsset.asset_key) == normalized_page_hint)
            )
            .order_by(PageAsset.asset_version.desc(), PageAsset.id)
        )
        page_asset = await self._exec_first(asset_statement)
        if page_asset is None:
            return None, None

        check_statement = select(PageCheck).where(PageCheck.page_asset_id == page_asset.id).where(
            (func.lower(PageCheck.goal) == normalized_goal)
            | (func.lower(PageCheck.check_code) == normalized_goal)
        ).order_by(PageCheck.id)
        page_check = await self._exec_first(check_statement)
        return page_asset, page_check

    async def create_execution_request(
        self,
        *,
        payload: CreateCheckRequest,
    ) -> ExecutionRequest:
        request = ExecutionRequest(**payload.model_dump())
        self.session.add(request)
        if isinstance(self.session, AsyncSession):
            await self.session.flush()
        else:
            self.session.flush()
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
        if isinstance(self.session, AsyncSession):
            await self.session.flush()
        else:
            self.session.flush()
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
        queued_jobs = await self._exec_all(select(QueuedJob))
        queued_job = next(
            (
                job
                for job in queued_jobs
                if job.payload.get("execution_request_id") == str(request_id)
            ),
            None,
        )

        return CheckRequestStatus(
            request_id=request.id,
            plan_id=plan.id if plan else None,
            page_check_id=plan.resolved_page_check_id if plan else None,
            execution_track=plan.execution_track if plan else None,
            auth_policy=plan.auth_policy if plan else None,
            status=queued_job.status if queued_job else "accepted",
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
            .where(PageAsset.status == AssetStatus.READY)
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
                )
                for check in checks
            ],
        )

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
