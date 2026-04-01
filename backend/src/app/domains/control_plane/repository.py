from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sqlalchemy import func
from sqlmodel import Session, select

from app.domains.control_plane.schemas import CreateCheckRequest
from app.shared.enums import AssetStatus
from app.infrastructure.db.models.assets import IntentAlias, PageAsset, PageCheck
from app.infrastructure.db.models.crawl import Page
from app.infrastructure.db.models.execution import ExecutionPlan, ExecutionRequest
from app.infrastructure.db.models.systems import System


class ControlPlaneRepository(Protocol):
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

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class SqlControlPlaneRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    async def resolve_system(self, *, system_hint: str) -> System | None:
        normalized_hint = system_hint.strip().lower()
        statement = select(System).where(
            (func.lower(System.code) == normalized_hint)
            | (func.lower(System.name) == normalized_hint)
        )
        return self.session.exec(statement).first()

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

            page_asset = self.session.exec(asset_statement).first()
            if page_asset is not None:
                check_statement = select(PageCheck).where(PageCheck.page_asset_id == page_asset.id).where(
                    (func.lower(PageCheck.goal) == normalized_goal)
                    | (func.lower(PageCheck.check_code) == normalized_goal)
                ).order_by(PageCheck.id)
                page_check = self.session.exec(check_statement).first()
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
        page_asset = self.session.exec(asset_statement).first()
        if page_asset is None:
            return None, None

        check_statement = select(PageCheck).where(PageCheck.page_asset_id == page_asset.id).where(
            (func.lower(PageCheck.goal) == normalized_goal)
            | (func.lower(PageCheck.check_code) == normalized_goal)
        ).order_by(PageCheck.id)
        page_check = self.session.exec(check_statement).first()
        return page_asset, page_check

    async def create_execution_request(
        self,
        *,
        payload: CreateCheckRequest,
    ) -> ExecutionRequest:
        request = ExecutionRequest(**payload.model_dump())
        self.session.add(request)
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
        self.session.flush()
        return plan

    async def commit(self) -> None:
        self.session.commit()

    async def rollback(self) -> None:
        self.session.rollback()
