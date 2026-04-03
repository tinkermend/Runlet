from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.domains.auth_service.crypto import CredentialCrypto, LocalCredentialCrypto
from app.domains.control_plane.scheduler_registry import (
    SchedulerRegistry,
    build_auth_policy_job_id,
    build_crawl_policy_job_id,
    build_published_job_id,
)
from app.domains.control_plane.schemas import (
    CrawlTriggerRequest,
    UpdateSystemAuthPolicy,
    UpdateSystemCrawlPolicy,
)
from app.domains.control_plane.system_admin_repository import (
    SqlSystemAdminRepository,
    SystemTeardownIds,
)
from app.domains.control_plane.system_admin_schemas import WebSystemManifest
from app.domains.runner_service.scheduler import CreatePublishedJobRequest
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
from app.shared.enums import QueuedJobStatus


class FormalJobExecutor(Protocol):
    async def run_auth_refresh(self, job_id: UUID) -> None: ...

    async def run_crawl(self, job_id: UUID) -> None: ...

    async def run_asset_compile(self, job_id: UUID) -> None: ...


@dataclass(frozen=True)
class OnboardSystemResult:
    system_id: UUID
    system_code: str
    page_check_id: UUID
    published_job_id: UUID
    scheduler_job_ids: list[str]


@dataclass(frozen=True)
class TeardownSystemResult:
    system_found: bool
    remaining_scheduler_job_ids: list[str]
    remaining_reference_tables: list[str]


class SystemAdminService:
    def __init__(
        self,
        *,
        repository: SqlSystemAdminRepository,
        control_plane_service,
        job_executor: FormalJobExecutor,
        crypto: CredentialCrypto | None = None,
        scheduler_registry: SchedulerRegistry | None = None,
    ) -> None:
        self.repository = repository
        self.control_plane_service = control_plane_service
        self.job_executor = job_executor
        self.crypto = crypto or LocalCredentialCrypto()
        self.scheduler_registry = scheduler_registry

    async def onboard_system(self, *, manifest: WebSystemManifest) -> OnboardSystemResult:
        system = await self.repository.upsert_system(
            code=manifest.system.code,
            name=manifest.system.name,
            base_url=manifest.system.base_url,
            framework_type=manifest.system.framework_type,
        )
        await self.repository.upsert_system_credentials(
            system_id=system.id,
            login_url=manifest.credential.login_url,
            username_encrypted=self.crypto.encrypt(manifest.credential.username),
            password_encrypted=self.crypto.encrypt(manifest.credential.password),
            auth_type=manifest.credential.auth_type,
            selectors=manifest.credential.selectors,
        )
        await self.repository.commit()

        try:
            await self._upsert_runtime_policies(
                system_id=system.id,
                manifest=manifest,
                auth_enabled=False,
                crawl_enabled=False,
            )

            auth_job = await self.control_plane_service.refresh_auth(system_id=system.id)
            await self.job_executor.run_auth_refresh(auth_job.job_id)
            await self._ensure_job_completed_successfully(
                job_id=auth_job.job_id,
                job_label="auth refresh job",
            )

            crawl_job = await self.control_plane_service.trigger_crawl(
                system_id=system.id,
                payload=CrawlTriggerRequest(
                    crawl_scope=manifest.crawl_policy.crawl_scope,
                    framework_hint=manifest.system.framework_type,
                ),
            )
            await self.job_executor.run_crawl(crawl_job.job_id)

            snapshot_id = await self.repository.get_successful_crawl_snapshot_id(
                job_id=crawl_job.job_id
            )
            compile_job = await self.repository.get_compile_job_for_snapshot(
                snapshot_id=snapshot_id
            )
            await self.job_executor.run_asset_compile(compile_job.id)
            await self._ensure_job_completed_successfully(
                job_id=compile_job.id,
                job_label="asset compile job",
            )

            publish_target = await self.repository.get_publish_target(
                system_id=system.id,
                check_goal=manifest.publish.check_goal,
            )
            if publish_target is None:
                raise ValueError(
                    f"page_check for goal {manifest.publish.check_goal} not found"
                )

            render_result = await self.control_plane_service.render_page_check_script(
                page_check_id=publish_target.page_check.id,
                render_mode="published",
            )
            published_job = await self.control_plane_service.create_published_job(
                payload=CreatePublishedJobRequest(
                    script_render_id=render_result.script_render_id,
                    page_check_id=publish_target.page_check.id,
                    schedule_expr=manifest.publish.schedule_expr,
                    trigger_source="system_admin",
                    enabled=manifest.publish.enabled,
                )
            )

            await self._upsert_runtime_policies(
                system_id=system.id,
                manifest=manifest,
                auth_enabled=manifest.auth_policy.enabled,
                crawl_enabled=manifest.crawl_policy.enabled,
            )
        except Exception:
            await self._disable_runtime_policies(
                system_id=system.id,
                manifest=manifest,
            )
            raise

        return OnboardSystemResult(
            system_id=system.id,
            system_code=system.code,
            page_check_id=publish_target.page_check.id,
            published_job_id=published_job.published_job_id,
            scheduler_job_ids=self._list_scheduler_job_ids(),
        )

    async def teardown_system(self, *, system_code: str) -> TeardownSystemResult:
        system = await self.repository.get_system_by_code(system_code=system_code)
        if system is None:
            return TeardownSystemResult(
                system_found=False,
                remaining_scheduler_job_ids=[],
                remaining_reference_tables=[],
            )

        teardown_ids = await self.repository.collect_system_teardown_ids(system=system)
        scheduler_job_ids = self._remove_scheduler_jobs(teardown_ids=teardown_ids)

        try:
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
                await self.repository.delete_by_ids(model=model, ids=ids)
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise

        remaining_reference_tables = await self.repository.list_remaining_reference_tables(
            teardown_ids=teardown_ids
        )
        remaining_scheduler_job_ids = self._remaining_scheduler_job_ids(
            scheduler_job_ids=scheduler_job_ids
        )
        if remaining_reference_tables or remaining_scheduler_job_ids:
            raise RuntimeError(
                "system teardown left residue: "
                f"tables={remaining_reference_tables}, "
                f"scheduler_jobs={remaining_scheduler_job_ids}"
            )

        return TeardownSystemResult(
            system_found=True,
            remaining_scheduler_job_ids=[],
            remaining_reference_tables=[],
        )

    def _list_scheduler_job_ids(self) -> list[str]:
        if self.scheduler_registry is None:
            return []
        return sorted(job.id for job in self.scheduler_registry.scheduler.get_jobs())

    def _remove_scheduler_jobs(self, *, teardown_ids: SystemTeardownIds) -> list[str]:
        scheduler_job_ids = [
            build_auth_policy_job_id(teardown_ids.system_id),
            build_crawl_policy_job_id(teardown_ids.system_id),
            *[
                build_published_job_id(published_job_id)
                for published_job_id in teardown_ids.published_job_ids
            ],
        ]
        if self.scheduler_registry is None:
            return scheduler_job_ids

        self.scheduler_registry.remove_job(build_auth_policy_job_id(teardown_ids.system_id))
        self.scheduler_registry.remove_job(build_crawl_policy_job_id(teardown_ids.system_id))
        for published_job_id in teardown_ids.published_job_ids:
            self.scheduler_registry.remove_job(build_published_job_id(published_job_id))
        return scheduler_job_ids

    def _remaining_scheduler_job_ids(self, *, scheduler_job_ids: list[str]) -> list[str]:
        if self.scheduler_registry is None:
            return []
        return sorted(
            job_id
            for job_id in scheduler_job_ids
            if self.scheduler_registry.scheduler.get_job(job_id) is not None
        )

    async def _ensure_job_completed_successfully(
        self,
        *,
        job_id: UUID,
        job_label: str,
    ) -> None:
        job = await self.repository.get_job(job_id=job_id)
        if job is None:
            raise ValueError(f"{job_label} {job_id} not found")
        if job.status == QueuedJobStatus.COMPLETED.value:
            return

        detail = job.status
        if job.failure_message:
            detail = f"{detail}: {job.failure_message}"
        raise ValueError(f"{job_label} {job_id} did not complete successfully: {detail}")

    async def _disable_runtime_policies(
        self,
        *,
        system_id: UUID,
        manifest: WebSystemManifest,
    ) -> None:
        await self._upsert_runtime_policies(
            system_id=system_id,
            manifest=manifest,
            auth_enabled=False,
            crawl_enabled=False,
        )

    async def _upsert_runtime_policies(
        self,
        *,
        system_id: UUID,
        manifest: WebSystemManifest,
        auth_enabled: bool,
        crawl_enabled: bool,
    ) -> None:
        await self.control_plane_service.upsert_system_auth_policy(
            system_id=system_id,
            payload=UpdateSystemAuthPolicy(
                enabled=auth_enabled,
                schedule_expr=manifest.auth_policy.schedule_expr,
                auth_mode=manifest.auth_policy.auth_mode,
                captcha_provider=manifest.auth_policy.captcha_provider,
            ),
        )
        await self.control_plane_service.upsert_system_crawl_policy(
            system_id=system_id,
            payload=UpdateSystemCrawlPolicy(
                enabled=crawl_enabled,
                schedule_expr=manifest.crawl_policy.schedule_expr,
                crawl_scope=manifest.crawl_policy.crawl_scope,
            ),
        )
