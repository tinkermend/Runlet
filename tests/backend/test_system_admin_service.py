from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlmodel import select

from app.domains.auth_service.crypto import LocalCredentialCrypto
from app.domains.auth_service.schemas import AuthRefreshResult
from app.domains.asset_compiler.service import AssetCompilerService
from app.domains.control_plane.job_types import (
    ASSET_COMPILE_JOB_TYPE,
    AUTH_REFRESH_JOB_TYPE,
    CRAWL_JOB_TYPE,
)
from app.domains.control_plane.repository import SqlControlPlaneRepository
from app.domains.control_plane.scheduler_registry import (
    SchedulerRegistry,
    build_auth_policy_job_id,
    build_crawl_policy_job_id,
    build_published_job_id,
)
from app.domains.control_plane.service import ControlPlaneService
from app.domains.control_plane.system_admin_schemas import WebSystemManifest
from app.domains.crawler_service.schemas import CrawlRunResult
from app.domains.runner_service.scheduler import PublishedJobService
from app.domains.runner_service.script_renderer import ScriptRenderer
from app.infrastructure.db.models.assets import ModulePlan, PageAsset, PageCheck
from app.infrastructure.db.models.crawl import CrawlSnapshot, MenuNode, Page, PageElement
from app.infrastructure.db.models.jobs import PublishedJob, QueuedJob
from app.infrastructure.db.models.runtime_policies import SystemAuthPolicy, SystemCrawlPolicy
from app.infrastructure.db.models.systems import AuthState, System, SystemCredential
from app.infrastructure.queue.dispatcher import SqlQueueDispatcher
from app.jobs.asset_compile_job import AssetCompileJobHandler
from app.jobs.auth_refresh_job import AuthRefreshJobHandler
from app.jobs.crawl_job import CrawlJobHandler
from app.shared.enums import AssetLifecycleStatus, AssetStatus


class StubAuthService:
    def __init__(self, db_session) -> None:
        self.db_session = db_session
        self.calls = []

    async def refresh_auth_state(self, *, system_id):
        self.calls.append(system_id)
        auth_state = AuthState(
            system_id=system_id,
            status="valid",
            storage_state={"cookies": [{"name": "sid", "value": "token"}]},
            cookies={"items": [{"name": "sid", "value": "token"}]},
            local_storage={"https://example.com": {"token": "abc"}},
            auth_mode="storage_state",
            is_valid=True,
            validated_at=datetime(2026, 4, 3, 8, 55, tzinfo=UTC),
        )
        self.db_session.add(auth_state)
        self.db_session.commit()
        self.db_session.refresh(auth_state)
        return AuthRefreshResult(
            system_id=system_id,
            status="success",
            auth_state_id=auth_state.id,
        )


class StubCrawlerService:
    def __init__(self, db_session) -> None:
        self.db_session = db_session
        self.calls = []

    async def run_crawl(self, *, system_id, crawl_scope: str) -> CrawlRunResult:
        system = self.db_session.get(System, system_id)
        assert system is not None
        self.calls.append({"system_id": system_id, "crawl_scope": crawl_scope})

        snapshot = CrawlSnapshot(
            system_id=system_id,
            crawl_type=crawl_scope,
            framework_detected=system.framework_type,
            quality_score=1.0,
            started_at=datetime(2026, 4, 3, 9, 0, tzinfo=UTC),
            finished_at=datetime(2026, 4, 3, 9, 1, tzinfo=UTC),
        )
        self.db_session.add(snapshot)
        self.db_session.flush()

        page = Page(
            system_id=system_id,
            snapshot_id=snapshot.id,
            route_path="/dashboard/users",
            page_title="用户列表",
            page_summary="用户列表页面",
        )
        self.db_session.add(page)
        self.db_session.flush()

        self.db_session.add(
            MenuNode(
                system_id=system_id,
                snapshot_id=snapshot.id,
                page_id=page.id,
                label="用户列表",
                route_path=page.route_path,
                depth=0,
                sort_order=0,
            )
        )

        self.db_session.add(
            PageElement(
                system_id=system_id,
                snapshot_id=snapshot.id,
                page_id=page.id,
                element_type="button",
                element_text="新增用户",
                usage_description="新增用户",
            )
        )
        if system.code in {"hotgo_test3", "vben_test1"}:
            self.db_session.add(
                PageElement(
                    system_id=system_id,
                    snapshot_id=snapshot.id,
                    page_id=page.id,
                    element_type="table",
                    element_role="table",
                    element_text="用户表格",
                    usage_description="列表表格",
                )
            )

        self.db_session.commit()
        self.db_session.refresh(snapshot)
        return CrawlRunResult(
            system_id=system_id,
            status="success",
            snapshot_id=snapshot.id,
            pages_saved=1,
            menus_saved=1,
            elements_saved=2 if system.code in {"hotgo_test3", "vben_test1"} else 1,
        )


class InProcessJobExecutor:
    def __init__(
        self,
        *,
        db_session,
        auth_service,
        crawler_service,
        control_plane_service,
        asset_compiler_service=None,
    ) -> None:
        handlers = {
            AUTH_REFRESH_JOB_TYPE: AuthRefreshJobHandler(
                session=db_session,
                auth_service=auth_service,
            ),
            CRAWL_JOB_TYPE: CrawlJobHandler(
                session=db_session,
                crawler_service=crawler_service,
            ),
            ASSET_COMPILE_JOB_TYPE: AssetCompileJobHandler(
                session=db_session,
                asset_compiler_service=asset_compiler_service or AssetCompilerService(session=db_session),
                control_plane_service=control_plane_service,
            ),
        }
        self.handlers = handlers

    async def run_auth_refresh(self, job_id) -> None:
        await self.handlers[AUTH_REFRESH_JOB_TYPE].run(job_id=job_id)

    async def run_crawl(self, job_id) -> None:
        await self.handlers[CRAWL_JOB_TYPE].run(job_id=job_id)

    async def run_asset_compile(self, job_id) -> None:
        await self.handlers[ASSET_COMPILE_JOB_TYPE].run(job_id=job_id)


def build_hotgo_manifest() -> WebSystemManifest:
    return WebSystemManifest.model_validate(
        {
            "system": {
                "code": "hotgo_test3",
                "name": "hotgo",
                "base_url": "https://hotgo.facms.cn",
                "framework_type": "react",
            },
            "credential": {
                "login_url": "https://hotgo.facms.cn/admin#/login?redirect=/dashboard",
                "username": "admin",
                "password": "123456",
                "auth_type": "image_captcha",
                "selectors": {
                    "username": "input[name=username]",
                    "password": "input[name=password]",
                    "submit": "button[type=submit]",
                },
            },
            "auth_policy": {
                "enabled": True,
                "schedule_expr": "*/30 * * * *",
                "auth_mode": "image_captcha",
                "captcha_provider": "ddddocr",
            },
            "crawl_policy": {
                "enabled": True,
                "schedule_expr": "0 */2 * * *",
                "crawl_scope": "full",
            },
            "publish": {
                "check_goal": "table_render",
                "schedule_expr": "*/30 * * * *",
                "enabled": True,
            },
        }
    )


def build_manifest_without_matching_check() -> WebSystemManifest:
    manifest = build_hotgo_manifest().model_copy(deep=True)
    manifest.system.code = "wms_test3"
    manifest.system.name = "wms"
    manifest.system.base_url = "https://wms.example.com"
    manifest.system.framework_type = "vue"
    manifest.credential.login_url = "https://wms.example.com/login"
    return manifest


@pytest.fixture
def system_admin_service_builder(db_session, scheduler):
    from app.domains.control_plane.system_admin_repository import SqlSystemAdminRepository
    from app.domains.control_plane.system_admin_service import SystemAdminService

    def build(
        *,
        control_plane_service=None,
        auth_service=None,
        crawler_service=None,
        asset_compiler_service=None,
    ):
        scheduler_registry = SchedulerRegistry(
            session=db_session,
            scheduler=scheduler,
        )
        dispatcher = SqlQueueDispatcher(db_session)
        resolved_control_plane_service = control_plane_service or ControlPlaneService(
            repository=SqlControlPlaneRepository(db_session),
            dispatcher=dispatcher,
            script_renderer=ScriptRenderer(session=db_session),
            published_job_service=PublishedJobService(session=db_session, dispatcher=dispatcher),
            scheduler_registry=scheduler_registry,
        )
        resolved_auth_service = auth_service or StubAuthService(db_session)
        resolved_crawler_service = crawler_service or StubCrawlerService(db_session)
        return SystemAdminService(
            repository=SqlSystemAdminRepository(db_session),
            control_plane_service=resolved_control_plane_service,
            crypto=LocalCredentialCrypto(secret="test-secret"),
            job_executor=InProcessJobExecutor(
                db_session=db_session,
                auth_service=resolved_auth_service,
                crawler_service=resolved_crawler_service,
                control_plane_service=resolved_control_plane_service,
                asset_compiler_service=asset_compiler_service,
            ),
            scheduler_registry=scheduler_registry,
        )

    return build


@pytest.fixture
def system_admin_service(system_admin_service_builder):
    return system_admin_service_builder()


@pytest.fixture
async def onboarded_system(system_admin_service):
    manifest = build_hotgo_manifest().model_copy(deep=True)
    manifest.system.code = "vben_test1"
    manifest.system.name = "vben"
    manifest.system.base_url = "https://vben.example.com"
    manifest.credential.login_url = "https://vben.example.com/login"
    return await system_admin_service.onboard_system(manifest=manifest)


def _seed_existing_publish_target(db_session) -> None:
    system = System(
        code="hotgo_test3",
        name="old hotgo",
        base_url="https://old-hotgo.example.com",
        framework_type="react",
    )
    db_session.add(system)
    db_session.flush()

    page = Page(
        system_id=system.id,
        route_path="/legacy/users",
        page_title="旧用户列表",
        page_summary="旧资产",
    )
    db_session.add(page)
    db_session.flush()

    page_asset = PageAsset(
        system_id=system.id,
        page_id=page.id,
        asset_key="hotgo_test3.legacy.users",
        asset_version="20260401000000",
        status=AssetStatus.SAFE,
    )
    db_session.add(page_asset)
    db_session.flush()

    module_plan = ModulePlan(
        page_asset_id=page_asset.id,
        check_code="table_render",
        plan_version="v1",
        steps_json=[
            {"module": "page.wait_ready", "params": {"route_path": page.route_path}},
            {"module": "assert.table_visible", "params": {"route_path": page.route_path}},
        ],
    )
    db_session.add(module_plan)
    db_session.flush()

    page_check = PageCheck(
        page_asset_id=page_asset.id,
        check_code="table_render",
        goal="table_render",
        module_plan_id=module_plan.id,
    )
    db_session.add(page_check)
    db_session.commit()


def _seed_publish_target_candidate(
    db_session,
    *,
    system_id,
    route_path: str,
    asset_key: str,
    asset_version: str,
    lifecycle_status: AssetLifecycleStatus = AssetLifecycleStatus.ACTIVE,
):
    page = Page(
        system_id=system_id,
        route_path=route_path,
        page_title=f"{route_path} 页面",
    )
    db_session.add(page)
    db_session.flush()

    page_asset = PageAsset(
        system_id=system_id,
        page_id=page.id,
        asset_key=asset_key,
        asset_version=asset_version,
        status=AssetStatus.SAFE,
        lifecycle_status=lifecycle_status,
    )
    db_session.add(page_asset)
    db_session.flush()

    module_plan = ModulePlan(
        page_asset_id=page_asset.id,
        check_code="table_render",
        plan_version="v1",
        steps_json=[{"module": "assert.table_visible", "params": {"route_path": route_path}}],
    )
    db_session.add(module_plan)
    db_session.flush()

    page_check = PageCheck(
        page_asset_id=page_asset.id,
        check_code="table_render",
        goal="table_render",
        module_plan_id=module_plan.id,
        lifecycle_status=lifecycle_status,
    )
    db_session.add(page_check)
    db_session.flush()
    return page_asset, page_check


def test_web_system_manifest_accepts_nested_yaml_sections() -> None:
    manifest = WebSystemManifest.model_validate(
        {
            "system": {
                "code": "hotgo_test3",
                "name": "hotgo",
                "base_url": "https://hotgo.facms.cn",
                "framework_type": "react",
            },
            "credential": {
                "login_url": "https://hotgo.facms.cn/admin#/login?redirect=/dashboard",
                "username": "admin",
                "password": "123456",
                "auth_type": "image_captcha",
                "selectors": {"username": "input[name=username]"},
            },
            "auth_policy": {
                "enabled": True,
                "schedule_expr": "*/30 * * * *",
                "auth_mode": "image_captcha",
                "captcha_provider": "ddddocr",
            },
            "crawl_policy": {
                "enabled": True,
                "schedule_expr": "0 */2 * * *",
                "crawl_scope": "full",
            },
            "publish": {
                "check_goal": "table_render",
                "schedule_expr": "*/30 * * * *",
                "enabled": True,
            },
        }
    )

    assert manifest.system.code == "hotgo_test3"
    assert manifest.publish.check_goal == "table_render"


def test_local_credential_crypto_round_trips_with_env_secret() -> None:
    crypto = LocalCredentialCrypto(secret="test-secret")
    encrypted = crypto.encrypt("admin")

    assert encrypted.startswith("enc-b64:")
    assert crypto.decrypt(encrypted) == "admin"


@pytest.mark.parametrize(
    ("section", "field_name"),
    [
        ("system", "code"),
        ("system", "name"),
        ("system", "base_url"),
        ("system", "framework_type"),
        ("credential", "login_url"),
        ("credential", "username"),
        ("credential", "password"),
        ("credential", "auth_type"),
        ("auth_policy", "schedule_expr"),
        ("auth_policy", "auth_mode"),
        ("crawl_policy", "schedule_expr"),
        ("publish", "check_goal"),
        ("publish", "schedule_expr"),
    ],
)
def test_web_system_manifest_rejects_empty_required_text_fields(
    section: str,
    field_name: str,
) -> None:
    payload = {
        "system": {
            "code": "hotgo_test3",
            "name": "hotgo",
            "base_url": "https://hotgo.facms.cn",
            "framework_type": "react",
        },
        "credential": {
            "login_url": "https://hotgo.facms.cn/admin#/login?redirect=/dashboard",
            "username": "admin",
            "password": "123456",
            "auth_type": "image_captcha",
            "selectors": {"username": "input[name=username]"},
        },
        "auth_policy": {
            "enabled": True,
            "schedule_expr": "*/30 * * * *",
            "auth_mode": "image_captcha",
            "captcha_provider": "ddddocr",
        },
        "crawl_policy": {
            "enabled": True,
            "schedule_expr": "0 */2 * * *",
            "crawl_scope": "full",
        },
        "publish": {
            "check_goal": "table_render",
            "schedule_expr": "*/30 * * * *",
            "enabled": True,
        },
    }
    payload[section][field_name] = "   "

    with pytest.raises(ValidationError):
        WebSystemManifest.model_validate(payload)


def test_local_credential_crypto_decrypt_supports_legacy_enc_prefix() -> None:
    crypto = LocalCredentialCrypto(secret="test-secret")

    assert crypto.decrypt("enc:legacy-admin") == "legacy-admin"


def test_local_credential_crypto_decrypt_supports_legacy_b64_without_secret_prefix() -> None:
    crypto = LocalCredentialCrypto(secret="test-secret")

    assert crypto.decrypt("enc-b64:bGVnYWN5LWFkbWlu") == "legacy-admin"


def test_web_system_manifest_rejects_non_string_required_text_with_validation_error() -> None:
    payload = {
        "system": {
            "code": 123,
            "name": "hotgo",
            "base_url": "https://hotgo.facms.cn",
            "framework_type": "react",
        },
        "credential": {
            "login_url": "https://hotgo.facms.cn/admin#/login?redirect=/dashboard",
            "username": "admin",
            "password": "123456",
            "auth_type": "image_captcha",
            "selectors": {"username": "input[name=username]"},
        },
        "auth_policy": {
            "enabled": True,
            "schedule_expr": "*/30 * * * *",
            "auth_mode": "image_captcha",
            "captcha_provider": "ddddocr",
        },
        "crawl_policy": {
            "enabled": True,
            "schedule_expr": "0 */2 * * *",
            "crawl_scope": "full",
        },
        "publish": {
            "check_goal": "table_render",
            "schedule_expr": "*/30 * * * *",
            "enabled": True,
        },
    }

    with pytest.raises(ValidationError):
        WebSystemManifest.model_validate(payload)


@pytest.mark.anyio
async def test_onboard_system_creates_records_runs_jobs_and_publishes(
    system_admin_service,
    scheduler,
    db_session,
):
    result = await system_admin_service.onboard_system(manifest=build_hotgo_manifest())

    system = db_session.exec(select(System).where(System.code == "hotgo_test3")).one()
    credential = db_session.exec(
        select(SystemCredential).where(SystemCredential.system_id == system.id)
    ).one()
    auth_policy = db_session.exec(
        select(SystemAuthPolicy).where(SystemAuthPolicy.system_id == system.id)
    ).one()
    crawl_policy = db_session.exec(
        select(SystemCrawlPolicy).where(SystemCrawlPolicy.system_id == system.id)
    ).one()
    auth_state = db_session.exec(select(AuthState).where(AuthState.system_id == system.id)).one()
    published_job = db_session.get(PublishedJob, result.published_job_id)
    queued_jobs = db_session.exec(select(QueuedJob).order_by(QueuedJob.created_at, QueuedJob.id)).all()

    assert result.system_code == "hotgo_test3"
    assert result.page_check_id is not None
    assert result.published_job_id is not None
    assert f"published_job:{result.published_job_id}" in result.scheduler_job_ids
    assert scheduler.get_job(f"published_job:{result.published_job_id}") is not None
    assert credential.login_username_encrypted != "admin"
    assert credential.login_password_encrypted != "123456"
    assert auth_policy.auth_mode == "image_captcha"
    assert crawl_policy.crawl_scope == "full"
    assert auth_state.system_id == system.id
    assert published_job is not None
    assert published_job.page_check_id == result.page_check_id
    assert [job.job_type for job in queued_jobs] == ["auth_refresh", "crawl", "asset_compile"]


@pytest.mark.anyio
async def test_onboard_system_fails_when_publish_goal_is_missing(
    system_admin_service,
):
    with pytest.raises(ValueError, match="page_check for goal table_render not found"):
        await system_admin_service.onboard_system(
            manifest=build_manifest_without_matching_check()
        )


@pytest.mark.anyio
async def test_onboard_system_stops_when_auth_refresh_does_not_complete_successfully(
    system_admin_service_builder,
    db_session,
    scheduler,
):
    class FailingAuthService:
        async def refresh_auth_state(self, *, system_id):
            return AuthRefreshResult(
                system_id=system_id,
                status="failed",
                message="login failed",
            )

    service = system_admin_service_builder(auth_service=FailingAuthService())

    with pytest.raises(
        ValueError,
        match="auth refresh job .* did not complete successfully: failed: login failed",
    ):
        await service.onboard_system(manifest=build_hotgo_manifest())

    system = db_session.exec(select(System).where(System.code == "hotgo_test3")).one()
    auth_policy = db_session.exec(
        select(SystemAuthPolicy).where(SystemAuthPolicy.system_id == system.id)
    ).one()
    crawl_policy = db_session.exec(
        select(SystemCrawlPolicy).where(SystemCrawlPolicy.system_id == system.id)
    ).one()
    queued_jobs = db_session.exec(select(QueuedJob).order_by(QueuedJob.created_at, QueuedJob.id)).all()

    assert auth_policy.enabled is False
    assert crawl_policy.enabled is False
    assert scheduler.get_job(build_auth_policy_job_id(system.id)) is None
    assert scheduler.get_job(build_crawl_policy_job_id(system.id)) is None
    assert [job.job_type for job in queued_jobs] == ["auth_refresh"]


@pytest.mark.anyio
async def test_onboard_system_stops_when_asset_compile_does_not_complete_successfully(
    system_admin_service_builder,
    db_session,
    scheduler,
):
    class FailingAssetCompilerService:
        async def compile_snapshot(self, *, snapshot_id):
            raise ValueError("compile failed")

    _seed_existing_publish_target(db_session)
    service = system_admin_service_builder(
        asset_compiler_service=FailingAssetCompilerService()
    )

    with pytest.raises(
        ValueError,
        match="asset compile job .* did not complete successfully: failed: compile failed",
    ):
        await service.onboard_system(manifest=build_hotgo_manifest())

    system = db_session.exec(select(System).where(System.code == "hotgo_test3")).one()
    auth_policy = db_session.exec(
        select(SystemAuthPolicy).where(SystemAuthPolicy.system_id == system.id)
    ).one()
    crawl_policy = db_session.exec(
        select(SystemCrawlPolicy).where(SystemCrawlPolicy.system_id == system.id)
    ).one()
    published_jobs = db_session.exec(select(PublishedJob)).all()

    assert auth_policy.enabled is False
    assert crawl_policy.enabled is False
    assert scheduler.get_job(build_auth_policy_job_id(system.id)) is None
    assert scheduler.get_job(build_crawl_policy_job_id(system.id)) is None
    assert published_jobs == []


@pytest.mark.anyio
async def test_onboard_system_does_not_leave_scheduled_policies_when_second_policy_upsert_fails(
    system_admin_service_builder,
    db_session,
    scheduler,
):
    dispatcher = SqlQueueDispatcher(db_session)
    base_control_plane_service = ControlPlaneService(
        repository=SqlControlPlaneRepository(db_session),
        dispatcher=dispatcher,
        script_renderer=ScriptRenderer(session=db_session),
        published_job_service=PublishedJobService(session=db_session, dispatcher=dispatcher),
        scheduler_registry=SchedulerRegistry(session=db_session, scheduler=scheduler),
    )

    class FailingSecondPolicyUpsertControlPlaneService:
        def __init__(self, inner) -> None:
            self.inner = inner
            self.calls = []

        async def upsert_system_auth_policy(self, *, system_id, payload):
            self.calls.append(("auth", payload.enabled))
            return await self.inner.upsert_system_auth_policy(system_id=system_id, payload=payload)

        async def upsert_system_crawl_policy(self, *, system_id, payload):
            self.calls.append(("crawl", payload.enabled))
            raise RuntimeError("crawl policy upsert failed")

        def __getattr__(self, name):
            return getattr(self.inner, name)

    service = system_admin_service_builder(
        control_plane_service=FailingSecondPolicyUpsertControlPlaneService(
            base_control_plane_service
        )
    )

    with pytest.raises(RuntimeError, match="crawl policy upsert failed"):
        await service.onboard_system(manifest=build_hotgo_manifest())

    system = db_session.exec(select(System).where(System.code == "hotgo_test3")).one()
    auth_policy = db_session.exec(
        select(SystemAuthPolicy).where(SystemAuthPolicy.system_id == system.id)
    ).one()
    crawl_policies = db_session.exec(
        select(SystemCrawlPolicy).where(SystemCrawlPolicy.system_id == system.id)
    ).all()

    assert auth_policy.enabled is False
    assert scheduler.get_job(build_auth_policy_job_id(system.id)) is None
    assert crawl_policies == []
    assert scheduler.get_job(build_crawl_policy_job_id(system.id)) is None
    assert db_session.exec(select(QueuedJob)).all() == []


@pytest.mark.anyio
async def test_get_publish_target_prefers_newest_active_asset(db_session):
    from app.domains.control_plane.system_admin_repository import SqlSystemAdminRepository

    system = System(
        code="publish_target_test",
        name="publish target",
        base_url="https://publish-target.example.com",
        framework_type="react",
    )
    db_session.add(system)
    db_session.flush()

    _retired_asset, _ = _seed_publish_target_candidate(
        db_session,
        system_id=system.id,
        route_path="/retired",
        asset_key="publish_target_test.retired",
        asset_version="20260403000000",
        lifecycle_status=AssetLifecycleStatus.RETIRED_MISSING,
    )
    old_asset, old_check = _seed_publish_target_candidate(
        db_session,
        system_id=system.id,
        route_path="/old",
        asset_key="publish_target_test.old",
        asset_version="20260401000000",
    )
    new_asset, new_check = _seed_publish_target_candidate(
        db_session,
        system_id=system.id,
        route_path="/new",
        asset_key="publish_target_test.new",
        asset_version="20260402000000",
    )
    db_session.commit()

    repo = SqlSystemAdminRepository(db_session)
    target = await repo.get_publish_target(
        system_id=system.id,
        check_goal="table_render",
    )

    assert target is not None
    assert target.page_asset.id == new_asset.id
    assert target.page_check.id == new_check.id
    assert target.page_asset.id != old_asset.id
    assert target.page_check.id != old_check.id


@pytest.mark.anyio
async def test_teardown_system_removes_related_rows_and_scheduler_jobs(
    onboarded_system,
    system_admin_service,
    scheduler,
):
    assert scheduler.get_job(build_auth_policy_job_id(onboarded_system.system_id)) is not None
    assert scheduler.get_job(build_crawl_policy_job_id(onboarded_system.system_id)) is not None
    assert scheduler.get_job(build_published_job_id(onboarded_system.published_job_id)) is not None

    result = await system_admin_service.teardown_system(system_code="vben_test1")

    assert result.system_found is True
    assert result.remaining_scheduler_job_ids == []
    assert result.remaining_reference_tables == []


@pytest.mark.anyio
async def test_teardown_system_is_idempotent_when_system_is_missing(system_admin_service):
    result = await system_admin_service.teardown_system(system_code="missing-system")

    assert result.system_found is False


@pytest.mark.anyio
async def test_get_publish_target_uses_stable_ordering_for_asset_version_ties(db_session):
    from app.domains.control_plane.system_admin_repository import SqlSystemAdminRepository

    system = System(
        code="publish_target_tie_test",
        name="publish target tie",
        base_url="https://publish-target-tie.example.com",
        framework_type="react",
    )
    db_session.add(system)
    db_session.flush()

    first_asset, first_check = _seed_publish_target_candidate(
        db_session,
        system_id=system.id,
        route_path="/a",
        asset_key="publish_target_tie_test.a",
        asset_version="20260402000000",
    )
    second_asset, second_check = _seed_publish_target_candidate(
        db_session,
        system_id=system.id,
        route_path="/b",
        asset_key="publish_target_tie_test.b",
        asset_version="20260402000000",
    )
    db_session.commit()

    expected_asset, expected_check = sorted(
        [(first_asset, first_check), (second_asset, second_check)],
        key=lambda pair: pair[0].id,
    )[0]

    repo = SqlSystemAdminRepository(db_session)
    target = await repo.get_publish_target(
        system_id=system.id,
        check_goal="table_render",
    )

    assert target is not None
    assert target.page_asset.id == expected_asset.id
    assert target.page_check.id == expected_check.id
