from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session, desc, select

from app.domains.control_plane.job_types import ASSET_COMPILE_JOB_TYPE, CRAWL_JOB_TYPE
from app.infrastructure.db.models.assets import PageAsset, PageCheck
from app.infrastructure.db.models.jobs import QueuedJob
from app.infrastructure.db.models.systems import System, SystemCredential
from app.shared.enums import AssetLifecycleStatus


@dataclass(frozen=True)
class PublishTarget:
    page_asset: PageAsset
    page_check: PageCheck


class SqlSystemAdminRepository:
    def __init__(self, session: Session | AsyncSession) -> None:
        self.session = session

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
