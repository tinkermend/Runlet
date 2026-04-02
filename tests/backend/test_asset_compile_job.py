import pytest
from sqlmodel import select

from app.domains.control_plane.job_types import ASSET_COMPILE_JOB_TYPE
from app.infrastructure.db.models.assets import PageAsset
from app.infrastructure.db.models.crawl import CrawlSnapshot, MenuNode, Page, PageElement
from app.infrastructure.db.models.jobs import QueuedJob
from app.workers.runner import WorkerRunner


@pytest.fixture
def queued_compile_job(db_session, seeded_system):
    snapshot = CrawlSnapshot(
        system_id=seeded_system.id,
        crawl_type="full",
        framework_detected=seeded_system.framework_type,
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
