from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine

from app.main import create_app
from app.infrastructure.db.base import BaseModel
from app.infrastructure.db.models.assets import IntentAlias, PageAsset, PageCheck
from app.infrastructure.db.models.crawl import Page
from app.infrastructure.db.models.systems import System
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
def seeded_asset(db_session: Session) -> PageAsset:
    system = System(
        code="erp",
        name="ERP",
        base_url="https://erp.example.com",
        framework_type="react",
    )
    db_session.add(system)
    db_session.flush()

    page = Page(
        system_id=system.id,
        route_path="/users",
        page_title="用户管理",
    )
    db_session.add(page)
    db_session.flush()

    page_asset = PageAsset(
        system_id=system.id,
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
