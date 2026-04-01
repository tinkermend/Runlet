from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlmodel import select

from app.domains.auth_service.browser_login import BrowserLoginFailure
from app.domains.auth_service.schemas import BrowserLoginResult
from app.domains.auth_service.service import AuthService
from app.infrastructure.db.models.crawl import CrawlSnapshot, MenuNode, Page, PageElement
from app.infrastructure.db.models.jobs import QueuedJob
from app.infrastructure.db.models.systems import AuthState, SystemCredential


def _upgrade_to_head(tmp_path: Path):
    project_root = Path(__file__).resolve().parents[2]
    backend_root = project_root / "backend"
    alembic_cfg = Config(str(backend_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_root / "alembic"))

    db_path = tmp_path / "auth-runtime.sqlite3"
    db_url = f"sqlite:///{db_path}"
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(alembic_cfg, "head")

    return create_engine(db_url)


def test_auth_and_crawl_models_expose_runtime_fields():
    assert hasattr(SystemCredential, "login_auth_type")
    assert hasattr(AuthState, "storage_state")
    assert hasattr(AuthState, "status")
    assert hasattr(CrawlSnapshot, "quality_score")
    assert hasattr(MenuNode, "playwright_locator")
    assert hasattr(Page, "page_summary")
    assert hasattr(PageElement, "playwright_locator")
    assert hasattr(PageElement, "stability_score")
    assert hasattr(PageElement, "usage_description")
    assert hasattr(QueuedJob, "status")
    assert hasattr(QueuedJob, "created_at")
    assert hasattr(QueuedJob, "started_at")
    assert hasattr(QueuedJob, "finished_at")
    assert hasattr(QueuedJob, "failure_message")


def test_auth_and_crawl_migration_exposes_runtime_fields(tmp_path):
    engine = _upgrade_to_head(tmp_path)
    try:
        inspector = inspect(engine)

        auth_state_columns = {column["name"] for column in inspector.get_columns("auth_states")}
        assert {"storage_state", "validated_at", "expires_at", "status"} <= auth_state_columns

        crawl_snapshot_columns = {
            column["name"] for column in inspector.get_columns("crawl_snapshots")
        }
        assert {
            "quality_score",
            "degraded",
            "framework_detected",
        } <= crawl_snapshot_columns

        menu_node_columns = {column["name"] for column in inspector.get_columns("menu_nodes")}
        assert {"playwright_locator"} <= menu_node_columns

        page_columns = {column["name"] for column in inspector.get_columns("pages")}
        assert {"page_summary"} <= page_columns

        page_element_columns = {column["name"] for column in inspector.get_columns("page_elements")}
        assert {
            "playwright_locator",
            "stability_score",
            "usage_description",
        } <= page_element_columns

        queued_job_columns = {column["name"] for column in inspector.get_columns("queued_jobs")}
        assert {"status", "created_at", "started_at", "finished_at", "failure_message"} <= queued_job_columns
    finally:
        engine.dispose()


class PrefixDecryptor:
    def decrypt(self, value: str, *, secret_ref: str | None = None) -> str:
        assert secret_ref == "local/test"
        return value.removeprefix("enc:")


class SuccessfulBrowserLoginAdapter:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def login(
        self,
        *,
        login_url: str,
        username: str,
        password: str,
        auth_type: str,
        selectors: dict[str, object] | None,
    ) -> BrowserLoginResult:
        self.calls.append(
            {
                "login_url": login_url,
                "username": username,
                "password": password,
                "auth_type": auth_type,
                "selectors": selectors,
            }
        )
        return BrowserLoginResult(
            storage_state={
                "cookies": [{"name": "sid", "value": "abc123"}],
                "origins": [
                    {
                        "origin": "https://erp.example.com",
                        "localStorage": [{"name": "token", "value": "xyz"}],
                    }
                ],
            },
            auth_mode="storage_state",
        )


class FailingBrowserLoginAdapter:
    async def login(
        self,
        *,
        login_url: str,
        username: str,
        password: str,
        auth_type: str,
        selectors: dict[str, object] | None,
    ) -> BrowserLoginResult:
        raise BrowserLoginFailure("login failed", retryable=False)


class RetryableFailingBrowserLoginAdapter:
    async def login(
        self,
        *,
        login_url: str,
        username: str,
        password: str,
        auth_type: str,
        selectors: dict[str, object] | None,
    ) -> BrowserLoginResult:
        raise BrowserLoginFailure("temporary login failure", retryable=True)


class InvalidStorageStateBrowserLoginAdapter:
    async def login(
        self,
        *,
        login_url: str,
        username: str,
        password: str,
        auth_type: str,
        selectors: dict[str, object] | None,
    ) -> BrowserLoginResult:
        return BrowserLoginResult(
            storage_state={
                "cookies": [{"name": "csrf"}],
                "origins": [{"origin": "https://erp.example.com", "localStorage": []}],
            },
            auth_mode="storage_state",
        )


class NonSerializableStorageStateBrowserLoginAdapter:
    async def login(
        self,
        *,
        login_url: str,
        username: str,
        password: str,
        auth_type: str,
        selectors: dict[str, object] | None,
    ) -> BrowserLoginResult:
        return BrowserLoginResult(
            storage_state={
                "cookies": [{"name": "sid", "value": "abc123"}],
                "origins": [{"origin": "https://erp.example.com", "localStorage": []}],
                "opaque": set(["not-json"]),
            },
            auth_mode="storage_state",
        )


@pytest.mark.anyio
async def test_refresh_auth_state_persists_valid_state(
    db_session,
    seeded_system_credentials,
):
    adapter = SuccessfulBrowserLoginAdapter()
    auth_service = AuthService(
        session=db_session,
        crypto=PrefixDecryptor(),
        browser_login=adapter,
    )

    result = await auth_service.refresh_auth_state(
        system_id=seeded_system_credentials.system_id
    )

    assert result.status == "success"
    assert result.auth_state_id is not None
    assert adapter.calls == [
        {
            "login_url": "https://erp.example.com/login",
            "username": "erp-user",
            "password": "erp-password",
            "auth_type": "form",
            "selectors": {
                "username": "#username",
                "password": "#password",
                "submit": "button[type=submit]",
            },
        }
    ]

    persisted_state = db_session.exec(select(AuthState)).one()
    assert persisted_state.id == result.auth_state_id
    assert persisted_state.system_id == seeded_system_credentials.system_id
    assert persisted_state.status == "valid"
    assert persisted_state.is_valid is True
    assert persisted_state.storage_state["cookies"][0]["name"] == "sid"


@pytest.mark.anyio
async def test_refresh_auth_state_marks_failure_when_login_fails(
    db_session,
    seeded_system_credentials,
):
    auth_service = AuthService(
        session=db_session,
        crypto=PrefixDecryptor(),
        browser_login=FailingBrowserLoginAdapter(),
    )

    result = await auth_service.refresh_auth_state(
        system_id=seeded_system_credentials.system_id
    )

    assert result.status == "failed"
    assert result.auth_state_id is None
    assert db_session.exec(select(AuthState)).all() == []


@pytest.mark.anyio
async def test_refresh_auth_state_marks_retryable_failure_when_login_is_transient(
    db_session,
    seeded_system_credentials,
):
    auth_service = AuthService(
        session=db_session,
        crypto=PrefixDecryptor(),
        browser_login=RetryableFailingBrowserLoginAdapter(),
    )

    result = await auth_service.refresh_auth_state(
        system_id=seeded_system_credentials.system_id
    )

    assert result.status == "retryable_failed"
    assert result.auth_state_id is None


@pytest.mark.anyio
async def test_refresh_auth_state_rejects_storage_state_without_real_auth_signals(
    db_session,
    seeded_system_credentials,
):
    auth_service = AuthService(
        session=db_session,
        crypto=PrefixDecryptor(),
        browser_login=InvalidStorageStateBrowserLoginAdapter(),
    )

    result = await auth_service.refresh_auth_state(
        system_id=seeded_system_credentials.system_id
    )

    assert result.status == "failed"
    assert result.message == "captured auth state is empty"
    assert db_session.exec(select(AuthState)).all() == []


@pytest.mark.anyio
async def test_refresh_auth_state_fails_when_multiple_credentials_exist(
    db_session,
    seeded_system_credentials,
):
    duplicate = SystemCredential(
        system_id=seeded_system_credentials.system_id,
        login_url=seeded_system_credentials.login_url,
        login_username_encrypted="enc:second-user",
        login_password_encrypted="enc:second-password",
        login_auth_type="form",
        login_selectors=seeded_system_credentials.login_selectors,
        secret_ref=seeded_system_credentials.secret_ref,
    )
    db_session.add(duplicate)
    db_session.commit()

    auth_service = AuthService(
        session=db_session,
        crypto=PrefixDecryptor(),
        browser_login=SuccessfulBrowserLoginAdapter(),
    )

    result = await auth_service.refresh_auth_state(
        system_id=seeded_system_credentials.system_id
    )

    assert result.status == "failed"
    assert result.message == "multiple system credentials found"
    assert db_session.exec(select(AuthState)).all() == []


@pytest.mark.anyio
async def test_refresh_auth_state_fails_when_storage_state_is_not_json_serializable(
    db_session,
    seeded_system_credentials,
):
    auth_service = AuthService(
        session=db_session,
        crypto=PrefixDecryptor(),
        browser_login=NonSerializableStorageStateBrowserLoginAdapter(),
    )

    result = await auth_service.refresh_auth_state(
        system_id=seeded_system_credentials.system_id
    )

    assert result.status == "failed"
    assert result.message == "captured auth state must be JSON serializable"
    assert db_session.exec(select(AuthState)).all() == []
