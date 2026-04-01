from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from app.infrastructure.db.session import create_session_factory


def test_create_session_factory_returns_sqlmodel_async_session():
    session_factory = create_session_factory(
        "postgresql+asyncpg://aiops:AIOps!1234@127.0.0.1:5432/runlet"
    )

    session = session_factory()

    assert isinstance(session, SQLModelAsyncSession)
    assert hasattr(session, "exec")
