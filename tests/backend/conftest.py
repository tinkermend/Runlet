from pathlib import Path
from uuid import uuid4

import anyio
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine
from sqlmodel import select

from app.main import create_app
from app.infrastructure.db.base import BaseModel
from app.infrastructure.db.models.assets import IntentAlias, PageAsset, PageCheck
from app.infrastructure.db.models.crawl import CrawlSnapshot, Page
from app.infrastructure.db.models.systems import System, SystemCredential
from app.shared.enums import AssetStatus


@pytest.fixture
def db_session(tmp_path: Path) -> Session:
    db_path = tmp_path / "control-plane.sqlite3"
    engine = create_engine(f"sqlite:///{db_path}")
    BaseModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def seeded_system(db_session: Session) -> System:
    system = System(
        code="erp",
        name="ERP",
        base_url="https://erp.example.com",
        framework_type="react",
    )
    db_session.add(system)
    db_session.commit()
    db_session.refresh(system)
    return system


@pytest.fixture
def seeded_page_asset(db_session: Session, seeded_system: System) -> PageAsset:
    page = Page(
        system_id=seeded_system.id,
        route_path="/users",
        page_title="用户管理",
    )
    db_session.add(page)
    db_session.flush()

    page_asset = PageAsset(
        system_id=seeded_system.id,
        page_id=page.id,
        asset_key="erp.users",
        asset_version="2026.04.01",
        status=AssetStatus.READY,
    )
    db_session.add(page_asset)
    db_session.flush()

    page_check = PageCheck(
        page_asset_id=page_asset.id,
        check_code="table_render",
        goal="table_render",
        module_plan_id=uuid4(),
    )
    intent_alias = IntentAlias(
        system_alias="ERP",
        page_alias="用户管理",
        check_alias="table_render",
        asset_key=page_asset.asset_key,
        source="seed",
    )
    db_session.add(page_check)
    db_session.add(intent_alias)
    db_session.commit()
    db_session.refresh(page_asset)

    return page_asset


@pytest.fixture
def seeded_asset(seeded_page_asset: PageAsset) -> PageAsset:
    return seeded_page_asset


@pytest.fixture
def seeded_page_check(db_session: Session, seeded_page_asset: PageAsset) -> PageCheck:
    statement = select(PageCheck).where(PageCheck.page_asset_id == seeded_page_asset.id)
    return db_session.exec(statement).one()


@pytest.fixture
def seeded_snapshot(db_session: Session, seeded_system: System) -> CrawlSnapshot:
    snapshot = CrawlSnapshot(
        system_id=seeded_system.id,
        crawl_type="full",
        framework_detected=seeded_system.framework_type,
    )
    db_session.add(snapshot)
    db_session.commit()
    db_session.refresh(snapshot)
    return snapshot


@pytest.fixture
def seeded_system_credentials(db_session: Session, seeded_system: System) -> SystemCredential:
    credential = SystemCredential(
        system_id=seeded_system.id,
        login_url=f"{seeded_system.base_url}/login",
        login_username_encrypted="enc:erp-user",
        login_password_encrypted="enc:erp-password",
        login_auth_type="form",
        login_selectors={
            "username": "#username",
            "password": "#password",
            "submit": "button[type=submit]",
        },
        secret_ref="local/test",
    )
    db_session.add(credential)
    db_session.commit()
    db_session.refresh(credential)
    return credential


@pytest.fixture
def seeded_asset_without_matching_check(db_session: Session) -> PageAsset:
    system = System(
        code="wms",
        name="WMS",
        base_url="https://wms.example.com",
        framework_type="vue",
    )
    db_session.add(system)
    db_session.flush()

    page = Page(
        system_id=system.id,
        route_path="/inventory",
        page_title="库存列表",
    )
    db_session.add(page)
    db_session.flush()

    page_asset = PageAsset(
        system_id=system.id,
        page_id=page.id,
        asset_key="wms.inventory",
        asset_version="2026.04.01",
        status=AssetStatus.READY,
    )
    db_session.add(page_asset)
    db_session.flush()

    intent_alias = IntentAlias(
        system_alias="WMS",
        page_alias="库存列表",
        check_alias="search_submit",
        asset_key=page_asset.asset_key,
        source="seed",
    )
    db_session.add(intent_alias)
    db_session.commit()
    db_session.refresh(page_asset)

    return page_asset


@pytest.fixture
def accepted_request(control_plane_service, seeded_page_asset):
    async def submit():
        return await control_plane_service.submit_check_request(
            system_hint="ERP",
            page_hint="用户管理",
            check_goal="table_render",
            strictness="balanced",
            time_budget_ms=20_000,
            request_source="skill",
        )

    return anyio.run(submit)


@pytest.fixture
def control_plane_service(db_session: Session):
    from app.domains.control_plane.repository import SqlControlPlaneRepository
    from app.domains.control_plane.service import ControlPlaneService
    from app.infrastructure.queue.dispatcher import SqlQueueDispatcher

    repository = SqlControlPlaneRepository(db_session)
    dispatcher = SqlQueueDispatcher(db_session)
    return ControlPlaneService(repository=repository, dispatcher=dispatcher)


@pytest.fixture
def client(control_plane_service):
    from app.api.deps import get_control_plane_service

    app = create_app()
    app.dependency_overrides[get_control_plane_service] = lambda: control_plane_service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
