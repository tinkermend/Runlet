from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.domains.auth_service.crypto import CredentialCrypto, LocalCredentialCrypto
from app.domains.control_plane.scheduler_registry import SchedulerRegistry
from app.domains.control_plane.schemas import (
    CrawlTriggerRequest,
    UpdateSystemAuthPolicy,
    UpdateSystemCrawlPolicy,
)
from app.domains.control_plane.system_admin_repository import SqlSystemAdminRepository
from app.domains.control_plane.system_admin_schemas import WebSystemManifest
from app.domains.runner_service.scheduler import CreatePublishedJobRequest
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

        await self.control_plane_service.upsert_system_auth_policy(
            system_id=system.id,
            payload=UpdateSystemAuthPolicy(
                enabled=manifest.auth_policy.enabled,
                schedule_expr=manifest.auth_policy.schedule_expr,
                auth_mode=manifest.auth_policy.auth_mode,
                captcha_provider=manifest.auth_policy.captcha_provider,
            ),
        )
        await self.control_plane_service.upsert_system_crawl_policy(
            system_id=system.id,
            payload=UpdateSystemCrawlPolicy(
                enabled=manifest.crawl_policy.enabled,
                schedule_expr=manifest.crawl_policy.schedule_expr,
                crawl_scope=manifest.crawl_policy.crawl_scope,
            ),
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
        return OnboardSystemResult(
            system_id=system.id,
            system_code=system.code,
            page_check_id=publish_target.page_check.id,
            published_job_id=published_job.published_job_id,
            scheduler_job_ids=self._list_scheduler_job_ids(),
        )

    def _list_scheduler_job_ids(self) -> list[str]:
        if self.scheduler_registry is None:
            return []
        return sorted(job.id for job in self.scheduler_registry.scheduler.get_jobs())

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
