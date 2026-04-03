from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session, desc, select

from app.domains.control_plane.job_types import ASSET_COMPILE_JOB_TYPE, CRAWL_JOB_TYPE
from app.infrastructure.db.models.assets import (
    AssetReconciliationAudit,
    AssetSnapshot,
    IntentAlias,
    ModulePlan,
    PageAsset,
    PageCheck,
)
from app.infrastructure.db.models.crawl import CrawlSnapshot, MenuNode, Page, PageElement
from app.infrastructure.db.models.execution import (
    ExecutionArtifact,
    ExecutionPlan,
    ExecutionRequest,
    ExecutionRun,
    ScriptRender,
)
from app.infrastructure.db.models.jobs import JobRun, PublishedJob, QueuedJob
from app.infrastructure.db.models.runtime_policies import SystemAuthPolicy, SystemCrawlPolicy
from app.infrastructure.db.models.systems import AuthState, System, SystemCredential
from app.shared.enums import AssetLifecycleStatus


@dataclass(frozen=True)
class PublishTarget:
    page_asset: PageAsset
    page_check: PageCheck


@dataclass(frozen=True)
class SystemTeardownIds:
    system_id: UUID
    system_code: str
    job_run_ids: list[UUID]
    published_job_ids: list[UUID]
    page_check_ids: list[UUID]
    page_asset_ids: list[UUID]
    intent_alias_ids: list[UUID]
    module_plan_ids: list[UUID]
    asset_snapshot_ids: list[UUID]
    reconciliation_audit_ids: list[UUID]
    page_ids: list[UUID]
    menu_node_ids: list[UUID]
    page_element_ids: list[UUID]
    crawl_snapshot_ids: list[UUID]
    auth_state_ids: list[UUID]
    system_credential_ids: list[UUID]
    auth_policy_ids: list[UUID]
    crawl_policy_ids: list[UUID]
    execution_plan_ids: list[UUID]
    execution_run_ids: list[UUID]
    execution_artifact_ids: list[UUID]
    execution_request_ids: list[UUID]
    script_render_ids: list[UUID]
    queued_job_ids: list[UUID]


class SqlSystemAdminRepository:
    def __init__(self, session: Session | AsyncSession) -> None:
        self.session = session

    async def get_system_by_code(self, *, system_code: str) -> System | None:
        statement = select(System).where(System.code == system_code)
        return await self._exec_first(statement)

    async def upsert_system(
        self,
        *,
        code: str,
        name: str,
        base_url: str,
        framework_type: str,
    ) -> System:
        statement = select(System).where(System.code == code)
        system = await self._exec_first(statement)
        if system is None:
            system = System(
                code=code,
                name=name,
                base_url=base_url,
                framework_type=framework_type,
            )
        else:
            system.name = name
            system.base_url = base_url
            system.framework_type = framework_type

        self.session.add(system)
        await self._flush()
        await self._refresh(system)
        return system

    async def upsert_system_credentials(
        self,
        *,
        system_id: UUID,
        login_url: str,
        username_encrypted: str,
        password_encrypted: str,
        auth_type: str,
        selectors: dict[str, object] | None,
        secret_ref: str | None = "local/system-admin",
    ) -> SystemCredential:
        statement = (
            select(SystemCredential)
            .where(SystemCredential.system_id == system_id)
            .order_by(SystemCredential.id)
        )
        credentials = await self._exec_all(statement)
        if len(credentials) > 1:
            raise ValueError("multiple system credentials found")

        credential = credentials[0] if credentials else None
        if credential is None:
            credential = SystemCredential(
                system_id=system_id,
                login_url=login_url,
                login_username_encrypted=username_encrypted,
                login_password_encrypted=password_encrypted,
                login_auth_type=auth_type,
                login_selectors=selectors,
                secret_ref=secret_ref,
            )
        else:
            credential.login_url = login_url
            credential.login_username_encrypted = username_encrypted
            credential.login_password_encrypted = password_encrypted
            credential.login_auth_type = auth_type
            credential.login_selectors = selectors
            credential.secret_ref = secret_ref

        self.session.add(credential)
        await self._flush()
        await self._refresh(credential)
        return credential

    async def get_successful_crawl_snapshot_id(self, *, job_id: UUID) -> UUID:
        job = await self._get(QueuedJob, job_id)
        if job is None or job.job_type != CRAWL_JOB_TYPE:
            raise ValueError(f"crawl job {job_id} not found")

        payload = job.result_payload or {}
        if payload.get("status") != "success":
            raise ValueError(f"crawl job {job_id} did not complete successfully")

        snapshot_id = payload.get("snapshot_id")
        if not isinstance(snapshot_id, str):
            raise ValueError(f"crawl job {job_id} does not contain snapshot_id")

        try:
            return UUID(snapshot_id)
        except ValueError as exc:
            raise ValueError(f"crawl job {job_id} contains invalid snapshot_id") from exc

    async def get_job(self, *, job_id: UUID) -> QueuedJob | None:
        return await self._get(QueuedJob, job_id)

    async def get_compile_job_for_snapshot(self, *, snapshot_id: UUID) -> QueuedJob:
        jobs = await self._exec_all(
            select(QueuedJob)
            .where(QueuedJob.job_type == ASSET_COMPILE_JOB_TYPE)
            .order_by(QueuedJob.created_at, QueuedJob.id)
        )
        snapshot_text = str(snapshot_id)
        for job in jobs:
            payload = job.payload or {}
            if payload.get("snapshot_id") == snapshot_text:
                return job

        raise ValueError(f"asset_compile job for snapshot {snapshot_id} not found")

    async def get_publish_target(
        self,
        *,
        system_id: UUID,
        check_goal: str,
    ) -> PublishTarget | None:
        statement = (
            select(PageAsset, PageCheck)
            .join(PageCheck, PageCheck.page_asset_id == PageAsset.id)
            .where(PageAsset.system_id == system_id)
            .where(PageAsset.lifecycle_status == AssetLifecycleStatus.ACTIVE)
            .where(PageCheck.lifecycle_status == AssetLifecycleStatus.ACTIVE)
            .where(PageCheck.goal == check_goal)
            .order_by(desc(PageAsset.asset_version), PageAsset.id, PageCheck.id)
        )
        row = await self._exec_first(statement)
        if row is None:
            return None
        page_asset, page_check = row
        return PublishTarget(page_asset=page_asset, page_check=page_check)

    async def collect_system_teardown_ids(self, *, system: System) -> SystemTeardownIds:
        system_id = system.id
        system_id_text = str(system_id)

        auth_policy_ids = await self._select_ids(
            select(SystemAuthPolicy.id)
            .where(SystemAuthPolicy.system_id == system_id)
            .order_by(SystemAuthPolicy.id)
        )
        crawl_policy_ids = await self._select_ids(
            select(SystemCrawlPolicy.id)
            .where(SystemCrawlPolicy.system_id == system_id)
            .order_by(SystemCrawlPolicy.id)
        )
        system_credential_ids = await self._select_ids(
            select(SystemCredential.id)
            .where(SystemCredential.system_id == system_id)
            .order_by(SystemCredential.id)
        )
        auth_state_ids = await self._select_ids(
            select(AuthState.id)
            .where(AuthState.system_id == system_id)
            .order_by(AuthState.id)
        )
        crawl_snapshot_ids = await self._select_ids(
            select(CrawlSnapshot.id)
            .where(CrawlSnapshot.system_id == system_id)
            .order_by(CrawlSnapshot.id)
        )
        page_ids = await self._select_ids(
            select(Page.id).where(Page.system_id == system_id).order_by(Page.id)
        )
        menu_node_ids = await self._select_ids(
            select(MenuNode.id).where(MenuNode.system_id == system_id).order_by(MenuNode.id)
        )
        page_element_ids = await self._select_ids(
            select(PageElement.id)
            .where(PageElement.system_id == system_id)
            .order_by(PageElement.id)
        )
        page_asset_ids = await self._select_ids(
            select(PageAsset.id).where(PageAsset.system_id == system_id).order_by(PageAsset.id)
        )
        page_check_ids = await self._select_ids_for_column(
            PageCheck.id,
            PageCheck.page_asset_id,
            page_asset_ids,
        )
        module_plan_ids = await self._select_ids_for_column(
            ModulePlan.id,
            ModulePlan.page_asset_id,
            page_asset_ids,
        )
        asset_snapshot_ids = await self._select_ids_for_column(
            AssetSnapshot.id,
            AssetSnapshot.page_asset_id,
            page_asset_ids,
        )
        reconciliation_audit_ids = await self._select_ids_for_column(
            AssetReconciliationAudit.id,
            AssetReconciliationAudit.snapshot_id,
            crawl_snapshot_ids,
        )
        intent_alias_ids = await self._select_ids(
            select(IntentAlias.id)
            .join(PageAsset, IntentAlias.asset_key == PageAsset.asset_key)
            .where(PageAsset.system_id == system_id)
            .distinct()
            .order_by(IntentAlias.id)
        )

        execution_request_ids = await self._select_ids(
            select(ExecutionRequest.id)
            .where(ExecutionRequest.system_hint == system.code)
            .order_by(ExecutionRequest.id)
        )
        execution_plan_ids = await self._select_ids(
            self._build_execution_plan_id_statement(
                system_id=system_id,
                page_asset_ids=page_asset_ids,
                page_check_ids=page_check_ids,
                module_plan_ids=module_plan_ids,
                execution_request_ids=execution_request_ids,
            )
        )
        if execution_plan_ids:
            execution_request_ids = _sorted_unique(
                execution_request_ids
                + await self._select_ids_for_column(
                    ExecutionPlan.execution_request_id,
                    ExecutionPlan.id,
                    execution_plan_ids,
                )
            )
        execution_run_ids = await self._select_ids_for_column(
            ExecutionRun.id,
            ExecutionRun.execution_plan_id,
            execution_plan_ids,
        )
        execution_artifact_ids = await self._select_ids_for_column(
            ExecutionArtifact.id,
            ExecutionArtifact.execution_run_id,
            execution_run_ids,
        )

        published_job_ids = await self._select_ids(
            self._build_published_job_id_statement(
                page_check_ids=page_check_ids,
                page_asset_ids=page_asset_ids,
                crawl_snapshot_ids=crawl_snapshot_ids,
            )
        )
        published_job_script_render_ids = await self._select_ids_for_column(
            PublishedJob.script_render_id,
            PublishedJob.id,
            published_job_ids,
        )
        script_render_ids = _sorted_unique(
            published_job_script_render_ids
            + await self._select_ids(
                self._build_script_render_id_statement(
                    execution_artifact_ids=execution_artifact_ids,
                    execution_plan_ids=execution_plan_ids,
                )
            )
        )

        queued_job_ids = await self._collect_queued_job_ids(
            system_id_text=system_id_text,
            crawl_snapshot_ids=crawl_snapshot_ids,
            auth_policy_ids=auth_policy_ids,
            crawl_policy_ids=crawl_policy_ids,
            execution_plan_ids=execution_plan_ids,
            execution_request_ids=execution_request_ids,
            page_check_ids=page_check_ids,
        )

        job_runs = await self._collect_job_runs(
            published_job_ids=published_job_ids,
            queued_job_ids=queued_job_ids,
            execution_run_ids=execution_run_ids,
            script_render_ids=script_render_ids,
            policy_ids=auth_policy_ids + crawl_policy_ids,
        )
        job_run_ids = _sorted_unique([job_run.id for job_run in job_runs])
        queued_job_ids = _sorted_unique(
            queued_job_ids
            + [job_run.queued_job_id for job_run in job_runs if job_run.queued_job_id is not None]
        )
        execution_run_ids = _sorted_unique(
            execution_run_ids
            + [
                job_run.execution_run_id
                for job_run in job_runs
                if job_run.execution_run_id is not None
            ]
        )
        script_render_ids = _sorted_unique(
            script_render_ids
            + [job_run.script_render_id for job_run in job_runs if job_run.script_render_id is not None]
        )
        execution_artifact_ids = _sorted_unique(
            execution_artifact_ids
            + await self._select_ids_for_column(
                ExecutionArtifact.id,
                ExecutionArtifact.execution_run_id,
                execution_run_ids,
            )
        )
        script_render_ids = _sorted_unique(
            script_render_ids
            + await self._select_ids(
                self._build_script_render_id_statement(
                    execution_artifact_ids=execution_artifact_ids,
                    execution_plan_ids=execution_plan_ids,
                )
            )
        )

        return SystemTeardownIds(
            system_id=system_id,
            system_code=system.code,
            job_run_ids=job_run_ids,
            published_job_ids=published_job_ids,
            page_check_ids=page_check_ids,
            page_asset_ids=page_asset_ids,
            intent_alias_ids=intent_alias_ids,
            module_plan_ids=module_plan_ids,
            asset_snapshot_ids=asset_snapshot_ids,
            reconciliation_audit_ids=reconciliation_audit_ids,
            page_ids=page_ids,
            menu_node_ids=menu_node_ids,
            page_element_ids=page_element_ids,
            crawl_snapshot_ids=crawl_snapshot_ids,
            auth_state_ids=auth_state_ids,
            system_credential_ids=system_credential_ids,
            auth_policy_ids=auth_policy_ids,
            crawl_policy_ids=crawl_policy_ids,
            execution_plan_ids=execution_plan_ids,
            execution_run_ids=execution_run_ids,
            execution_artifact_ids=execution_artifact_ids,
            execution_request_ids=execution_request_ids,
            script_render_ids=script_render_ids,
            queued_job_ids=queued_job_ids,
        )

    async def delete_by_ids(self, *, model: type, ids: list[UUID]) -> None:
        if not ids:
            return

        statement = delete(model).where(model.id.in_(ids))
        if isinstance(self.session, AsyncSession):
            await self.session.exec(statement)
            return
        self.session.exec(statement)

    async def list_remaining_reference_tables(
        self,
        *,
        teardown_ids: SystemTeardownIds,
    ) -> list[str]:
        remaining_tables: list[str] = []
        for model, ids in [
            (JobRun, teardown_ids.job_run_ids),
            (PublishedJob, teardown_ids.published_job_ids),
            (QueuedJob, teardown_ids.queued_job_ids),
            (ExecutionArtifact, teardown_ids.execution_artifact_ids),
            (ScriptRender, teardown_ids.script_render_ids),
            (ExecutionRun, teardown_ids.execution_run_ids),
            (ExecutionPlan, teardown_ids.execution_plan_ids),
            (ExecutionRequest, teardown_ids.execution_request_ids),
            (AssetReconciliationAudit, teardown_ids.reconciliation_audit_ids),
            (AssetSnapshot, teardown_ids.asset_snapshot_ids),
            (ModulePlan, teardown_ids.module_plan_ids),
            (IntentAlias, teardown_ids.intent_alias_ids),
            (PageCheck, teardown_ids.page_check_ids),
            (PageAsset, teardown_ids.page_asset_ids),
            (PageElement, teardown_ids.page_element_ids),
            (MenuNode, teardown_ids.menu_node_ids),
            (Page, teardown_ids.page_ids),
            (CrawlSnapshot, teardown_ids.crawl_snapshot_ids),
            (AuthState, teardown_ids.auth_state_ids),
            (SystemCredential, teardown_ids.system_credential_ids),
            (SystemAuthPolicy, teardown_ids.auth_policy_ids),
            (SystemCrawlPolicy, teardown_ids.crawl_policy_ids),
            (System, [teardown_ids.system_id]),
        ]:
            if ids and await self._has_any_rows(model=model, ids=ids):
                remaining_tables.append(model.__tablename__)

        return remaining_tables

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

    async def _select_ids(self, statement) -> list[UUID]:
        return _sorted_unique(await self._exec_all(statement))

    async def _select_ids_for_column(self, target_column, filter_column, filter_ids: list[UUID]) -> list[UUID]:
        if not filter_ids:
            return []
        statement = select(target_column).where(filter_column.in_(filter_ids)).order_by(target_column)
        return await self._select_ids(statement)

    async def _has_any_rows(self, *, model: type, ids: list[UUID]) -> bool:
        statement = select(model.id).where(model.id.in_(ids)).limit(1)
        return await self._exec_first(statement) is not None

    def _build_execution_plan_id_statement(
        self,
        *,
        system_id: UUID,
        page_asset_ids: list[UUID],
        page_check_ids: list[UUID],
        module_plan_ids: list[UUID],
        execution_request_ids: list[UUID],
    ):
        clauses = [ExecutionPlan.resolved_system_id == system_id]
        if page_asset_ids:
            clauses.append(ExecutionPlan.resolved_page_asset_id.in_(page_asset_ids))
        if page_check_ids:
            clauses.append(ExecutionPlan.resolved_page_check_id.in_(page_check_ids))
        if module_plan_ids:
            clauses.append(ExecutionPlan.module_plan_id.in_(module_plan_ids))
        if execution_request_ids:
            clauses.append(ExecutionPlan.execution_request_id.in_(execution_request_ids))
        return select(ExecutionPlan.id).where(or_(*clauses)).order_by(ExecutionPlan.id)

    def _build_published_job_id_statement(
        self,
        *,
        page_check_ids: list[UUID],
        page_asset_ids: list[UUID],
        crawl_snapshot_ids: list[UUID],
    ):
        clauses = []
        if page_check_ids:
            clauses.extend(
                [
                    PublishedJob.page_check_id.in_(page_check_ids),
                    PublishedJob.paused_by_page_check_id.in_(page_check_ids),
                ]
            )
        if page_asset_ids:
            clauses.append(PublishedJob.paused_by_asset_id.in_(page_asset_ids))
        if crawl_snapshot_ids:
            clauses.append(PublishedJob.paused_by_snapshot_id.in_(crawl_snapshot_ids))
        if not clauses:
            return select(PublishedJob.id).where(PublishedJob.id.in_([]))
        return select(PublishedJob.id).where(or_(*clauses)).order_by(PublishedJob.id)

    def _build_script_render_id_statement(
        self,
        *,
        execution_artifact_ids: list[UUID],
        execution_plan_ids: list[UUID],
    ):
        clauses = []
        if execution_artifact_ids:
            clauses.append(ScriptRender.execution_artifact_id.in_(execution_artifact_ids))
        if execution_plan_ids:
            clauses.append(ScriptRender.execution_plan_id.in_(execution_plan_ids))
        if not clauses:
            return select(ScriptRender.id).where(ScriptRender.id.in_([]))
        return select(ScriptRender.id).where(or_(*clauses)).order_by(ScriptRender.id)

    async def _collect_queued_job_ids(
        self,
        *,
        system_id_text: str,
        crawl_snapshot_ids: list[UUID],
        auth_policy_ids: list[UUID],
        crawl_policy_ids: list[UUID],
        execution_plan_ids: list[UUID],
        execution_request_ids: list[UUID],
        page_check_ids: list[UUID],
    ) -> list[UUID]:
        snapshot_id_texts = {str(identifier) for identifier in crawl_snapshot_ids}
        policy_ids = {str(identifier) for identifier in auth_policy_ids + crawl_policy_ids}
        execution_plan_id_texts = {str(identifier) for identifier in execution_plan_ids}
        execution_request_id_texts = {str(identifier) for identifier in execution_request_ids}
        page_check_id_texts = {str(identifier) for identifier in page_check_ids}

        queued_jobs = await self._exec_all(select(QueuedJob).order_by(QueuedJob.id))
        queued_job_ids: list[UUID] = []
        for job in queued_jobs:
            payload = job.payload or {}
            result_payload = job.result_payload or {}
            if job.policy_id is not None and str(job.policy_id) in policy_ids:
                queued_job_ids.append(job.id)
                continue
            if payload.get("system_id") == system_id_text:
                queued_job_ids.append(job.id)
                continue
            if payload.get("snapshot_id") in snapshot_id_texts:
                queued_job_ids.append(job.id)
                continue
            if result_payload.get("snapshot_id") in snapshot_id_texts:
                queued_job_ids.append(job.id)
                continue
            if payload.get("execution_plan_id") in execution_plan_id_texts:
                queued_job_ids.append(job.id)
                continue
            if payload.get("execution_request_id") in execution_request_id_texts:
                queued_job_ids.append(job.id)
                continue
            if payload.get("page_check_id") in page_check_id_texts:
                queued_job_ids.append(job.id)
                continue

        return _sorted_unique(queued_job_ids)

    async def _collect_job_runs(
        self,
        *,
        published_job_ids: list[UUID],
        queued_job_ids: list[UUID],
        execution_run_ids: list[UUID],
        script_render_ids: list[UUID],
        policy_ids: list[UUID],
    ) -> list[JobRun]:
        clauses = []
        if published_job_ids:
            clauses.append(JobRun.published_job_id.in_(published_job_ids))
        if queued_job_ids:
            clauses.append(JobRun.queued_job_id.in_(queued_job_ids))
        if execution_run_ids:
            clauses.append(JobRun.execution_run_id.in_(execution_run_ids))
        if script_render_ids:
            clauses.append(JobRun.script_render_id.in_(script_render_ids))
        if policy_ids:
            clauses.append(JobRun.policy_id.in_(policy_ids))
        if not clauses:
            return []
        statement = select(JobRun).where(or_(*clauses)).order_by(JobRun.id)
        return await self._exec_all(statement)

    async def commit(self) -> None:
        if isinstance(self.session, AsyncSession):
            await self.session.commit()
            return
        self.session.commit()

    async def rollback(self) -> None:
        if isinstance(self.session, AsyncSession):
            await self.session.rollback()
            return
        self.session.rollback()


def _sorted_unique(values: list[UUID]) -> list[UUID]:
    return sorted({value for value in values if value is not None}, key=str)
