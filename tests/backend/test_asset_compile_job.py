import json
from uuid import UUID, uuid4

import pytest
from sqlmodel import select

from app.domains.asset_compiler.schemas import CompileSnapshotResult
from app.domains.control_plane.job_types import ASSET_COMPILE_JOB_TYPE
from app.domains.control_plane.repository import SqlControlPlaneRepository
from app.domains.control_plane.service import ControlPlaneService
from app.domains.runner_service.scheduler import PublishedJobService
from app.infrastructure.db.models.assets import IntentAlias, PageAsset
from app.infrastructure.db.models.crawl import CrawlSnapshot, MenuNode, Page, PageElement
from app.infrastructure.db.models.jobs import QueuedJob
from app.jobs.asset_compile_job import _serialize_compile_result
from app.infrastructure.queue.dispatcher import SqlQueueDispatcher
from app.shared.enums import AssetStatus
from app.workers.runner import WorkerRunner


@pytest.fixture
def queued_compile_job(db_session, seeded_system):
    snapshot = CrawlSnapshot(
        system_id=seeded_system.id,
        crawl_type="full",
        framework_detected=seeded_system.framework_type,
        quality_score=0.95,
    )
    db_session.add(snapshot)
    db_session.flush()

    page = Page(
        system_id=seeded_system.id,
        snapshot_id=snapshot.id,
        route_path="/users",
        page_title="用户管理",
        page_summary="用户管理列表，支持新增用户",
    )
    db_session.add(page)
    db_session.flush()

    db_session.add(
        MenuNode(
            system_id=seeded_system.id,
            snapshot_id=snapshot.id,
            page_id=page.id,
            label="系统管理",
            depth=0,
            sort_order=1,
        )
    )
    db_session.add(
        MenuNode(
            system_id=seeded_system.id,
            snapshot_id=snapshot.id,
            page_id=page.id,
            label="用户管理",
            route_path="/users",
            depth=1,
            sort_order=1,
        )
    )
    db_session.add(
        PageElement(
            system_id=seeded_system.id,
            snapshot_id=snapshot.id,
            page_id=page.id,
            element_type="table",
            element_role="table",
            element_text="用户列表",
            playwright_locator="get_by_role('table', name='用户列表')",
            usage_description="展示用户列表",
        )
    )
    db_session.add(
        PageElement(
            system_id=seeded_system.id,
            snapshot_id=snapshot.id,
            page_id=page.id,
            element_type="button",
            element_role="button",
            element_text="新增用户",
            playwright_locator="get_by_role('button', name='新增用户')",
            usage_description="打开新增用户弹窗",
        )
    )

    job = QueuedJob(
        job_type=ASSET_COMPILE_JOB_TYPE,
        payload={"snapshot_id": str(snapshot.id), "compile_scope": "impacted_pages_only"},
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


@pytest.mark.anyio
async def test_asset_compile_job_completes_and_persists_assets(
    db_session,
    queued_compile_job,
):
    from app.domains.asset_compiler.service import AssetCompilerService
    from app.jobs.asset_compile_job import AssetCompileJobHandler

    job_runner = WorkerRunner(
        session=db_session,
        handlers={
            ASSET_COMPILE_JOB_TYPE: AssetCompileJobHandler(
                session=db_session,
                asset_compiler_service=AssetCompilerService(session=db_session),
            )
        },
    )

    await job_runner.run_once()

    refreshed = db_session.get(QueuedJob, queued_compile_job.id)
    assets = db_session.exec(select(PageAsset)).all()

    assert refreshed is not None
    assert refreshed.status == "completed"
    assert refreshed.result_payload is not None
    assert refreshed.result_payload["status"] == "success"
    assert assets


def test_serialize_compile_result_json_safely_handles_reconciliation_uuid_lists():
    alias_id = uuid4()
    published_job_id = uuid4()
    reason_asset_id = uuid4()
    reason_check_id = uuid4()
    result = CompileSnapshotResult(
        snapshot_id=uuid4(),
        status="success",
        assets_created=1,
        assets_updated=2,
        assets_retired=3,
        checks_created=1,
        checks_updated=2,
        checks_retired=4,
        alias_disable_decision_count=5,
        alias_enable_decision_count=6,
        published_job_pause_decision_count=6,
        published_job_resume_decision_count=7,
        drift_state=AssetStatus.SAFE,
        asset_ids=[uuid4()],
        check_ids=[uuid4()],
        alias_ids_to_disable=[alias_id],
        alias_ids_to_enable=[alias_id],
        published_job_ids_to_pause=[published_job_id],
        published_job_ids_to_resume=[published_job_id],
        retire_reasons=[
            {
                "asset_id": reason_asset_id,
                "meta": {"check_id": reason_check_id},
            }
        ],
    )

    payload = _serialize_compile_result(result)

    assert payload["alias_ids_to_disable"] == [str(alias_id)]
    assert payload["published_job_ids_to_pause"] == [str(published_job_id)]
    assert payload["assets_retired"] == 3
    assert payload["checks_retired"] == 4
    assert payload["alias_disable_decision_count"] == 5
    assert payload["alias_enable_decision_count"] == 6
    assert payload["published_job_pause_decision_count"] == 6
    assert payload["published_job_resume_decision_count"] == 7
    assert payload["alias_ids_to_enable"] == [str(alias_id)]
    assert payload["published_job_ids_to_resume"] == [str(published_job_id)]
    assert payload["retire_reasons"] == [
        {
            "asset_id": str(reason_asset_id),
            "meta": {"check_id": str(reason_check_id)},
        }
    ]
    json.dumps(payload)


@pytest.mark.anyio
async def test_asset_compile_job_applies_control_plane_reconciliation_cascades(
    db_session,
    seeded_asset,
    seeded_page_check,
    seeded_snapshot,
    seeded_published_job,
):
    intent_alias = db_session.exec(
        select(IntentAlias).where(IntentAlias.asset_key == seeded_asset.asset_key)
    ).one()

    job = QueuedJob(
        job_type=ASSET_COMPILE_JOB_TYPE,
        payload={"snapshot_id": str(seeded_snapshot.id), "compile_scope": "impacted_pages_only"},
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    class StubAssetCompilerService:
        async def compile_snapshot(self, *, snapshot_id):
            return CompileSnapshotResult(
                snapshot_id=snapshot_id,
                status="success",
                assets_created=0,
                checks_created=0,
                assets_retired=1,
                checks_retired=1,
                drift_state=AssetStatus.SAFE,
                alias_disable_decision_count=1,
                published_job_pause_decision_count=1,
                alias_ids_to_disable=[intent_alias.id],
                published_job_ids_to_pause=[seeded_published_job.id],
                retire_reasons=[
                    {
                        "reason": "retired_missing",
                        "page_asset_id": seeded_asset.id,
                        "page_check_ids": [seeded_page_check.id],
                    }
                ],
            )

    dispatcher = SqlQueueDispatcher(db_session)
    control_plane_service = ControlPlaneService(
        repository=SqlControlPlaneRepository(db_session),
        dispatcher=dispatcher,
        published_job_service=PublishedJobService(session=db_session, dispatcher=dispatcher),
    )

    from app.jobs.asset_compile_job import AssetCompileJobHandler

    runner = WorkerRunner(
        session=db_session,
        handlers={
            ASSET_COMPILE_JOB_TYPE: AssetCompileJobHandler(
                session=db_session,
                asset_compiler_service=StubAssetCompilerService(),
                control_plane_service=control_plane_service,
            )
        },
    )

    await runner.run_once()

    refreshed = db_session.get(QueuedJob, job.id)
    db_session.refresh(intent_alias)
    db_session.refresh(seeded_published_job)

    assert refreshed is not None
    assert refreshed.status == "completed"
    assert refreshed.result_payload is not None
    assert refreshed.result_payload["alias_disable_decision_count"] == 1
    assert refreshed.result_payload["published_job_pause_decision_count"] == 1
    assert refreshed.result_payload["aliases_disabled"] == 1
    assert refreshed.result_payload["published_jobs_paused"] == 1
    assert intent_alias.is_active is False
    assert seeded_published_job.state == "paused"


@pytest.mark.anyio
async def test_asset_compile_job_applies_control_plane_recovery_cascades(
    db_session,
    seeded_asset,
    seeded_snapshot,
    seeded_published_job,
):
    intent_alias = db_session.exec(
        select(IntentAlias).where(IntentAlias.asset_key == seeded_asset.asset_key)
    ).one()
    intent_alias.is_active = False
    intent_alias.disabled_reason = "retired_missing"
    intent_alias.disabled_by_snapshot_id = seeded_snapshot.id
    seeded_published_job.state = "paused"
    seeded_published_job.pause_reason = "asset_retired_missing"
    seeded_published_job.paused_by_snapshot_id = seeded_snapshot.id
    seeded_published_job.paused_by_page_check_id = seeded_published_job.page_check_id
    db_session.add(intent_alias)
    db_session.add(seeded_published_job)
    db_session.commit()

    job = QueuedJob(
        job_type=ASSET_COMPILE_JOB_TYPE,
        payload={"snapshot_id": str(seeded_snapshot.id), "compile_scope": "impacted_pages_only"},
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    class StubAssetCompilerService:
        async def compile_snapshot(self, *, snapshot_id):
            return CompileSnapshotResult(
                snapshot_id=snapshot_id,
                status="success",
                assets_created=0,
                checks_created=0,
                drift_state=AssetStatus.SAFE,
                alias_enable_decision_count=1,
                published_job_resume_decision_count=1,
                alias_ids_to_enable=[intent_alias.id],
                published_job_ids_to_resume=[seeded_published_job.id],
            )

    dispatcher = SqlQueueDispatcher(db_session)
    control_plane_service = ControlPlaneService(
        repository=SqlControlPlaneRepository(db_session),
        dispatcher=dispatcher,
        published_job_service=PublishedJobService(session=db_session, dispatcher=dispatcher),
    )

    from app.jobs.asset_compile_job import AssetCompileJobHandler

    runner = WorkerRunner(
        session=db_session,
        handlers={
            ASSET_COMPILE_JOB_TYPE: AssetCompileJobHandler(
                session=db_session,
                asset_compiler_service=StubAssetCompilerService(),
                control_plane_service=control_plane_service,
            )
        },
    )

    await runner.run_once()

    refreshed = db_session.get(QueuedJob, job.id)
    db_session.refresh(intent_alias)
    db_session.refresh(seeded_published_job)

    assert refreshed is not None
    assert refreshed.status == "completed"
    assert refreshed.result_payload is not None
    assert refreshed.result_payload["alias_enable_decision_count"] == 1
    assert refreshed.result_payload["published_job_resume_decision_count"] == 1
    assert refreshed.result_payload["aliases_enabled"] == 1
    assert refreshed.result_payload["published_jobs_resumed"] == 1
    assert intent_alias.is_active is True
    assert intent_alias.disabled_reason is None
    assert seeded_published_job.state == "active"
    assert seeded_published_job.pause_reason is None


@pytest.mark.anyio
async def test_asset_compile_job_rolls_back_snapshot_switch_when_compile_raises(
    db_session,
    queued_compile_job,
):
    from app.jobs.asset_compile_job import AssetCompileJobHandler

    snapshot_id = UUID(queued_compile_job.payload["snapshot_id"])

    class FailingAssetCompilerService:
        async def compile_snapshot(self, *, snapshot_id):
            snapshot = db_session.get(CrawlSnapshot, snapshot_id)
            assert snapshot is not None
            snapshot.state = "active"
            db_session.add(snapshot)
            db_session.flush()
            raise RuntimeError("compile failed after switch")

    runner = WorkerRunner(
        session=db_session,
        handlers={
            ASSET_COMPILE_JOB_TYPE: AssetCompileJobHandler(
                session=db_session,
                asset_compiler_service=FailingAssetCompilerService(),
            )
        },
    )

    await runner.run_once()

    refreshed_job = db_session.get(QueuedJob, queued_compile_job.id)
    refreshed_snapshot = db_session.get(CrawlSnapshot, snapshot_id)

    assert refreshed_job is not None
    assert refreshed_job.status == "failed"
    assert refreshed_snapshot is not None
    assert refreshed_snapshot.state == "draft"
