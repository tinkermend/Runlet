import pytest

from app.domains.crawler_service.extractors.router_runtime import RuntimeRouteHintExtractor
from app.domains.crawler_service.extractors.app_readiness import evaluate_app_readiness
from app.domains.crawler_service.extractors.route_resolution import resolve_route_snapshot


def test_resolve_route_prefers_hash_route_over_pathname() -> None:
    snapshot = resolve_route_snapshot(
        pathname="/",
        location_hash="#/dashboard",
        router_route=None,
        history_route=None,
    )

    assert snapshot.resolved_route == "/dashboard"
    assert snapshot.route_source == "hash"


def test_resolve_route_prefers_router_before_hash_and_history() -> None:
    snapshot = resolve_route_snapshot(
        pathname="/from-pathname",
        location_hash="#/from-hash",
        router_route="/from-router",
        history_route="/from-history",
    )

    assert snapshot.resolved_route == "/from-router"
    assert snapshot.route_source == "router"


def test_resolve_route_uses_history_when_router_and_hash_missing() -> None:
    snapshot = resolve_route_snapshot(
        pathname="/from-pathname",
        location_hash="",
        router_route=None,
        history_route="/from-history",
    )

    assert snapshot.resolved_route == "/from-history"
    assert snapshot.route_source == "history"


def test_resolve_route_normalizes_query_and_fragment() -> None:
    snapshot = resolve_route_snapshot(
        pathname="/users/?tab=all#section",
        location_hash="#/ignored?x=1",
        router_route="/users/?from=router#detail",
        history_route=None,
    )

    assert snapshot.resolved_route == "/users"
    assert snapshot.pathname == "/users"
    assert snapshot.router_route == "/users"


def test_app_readiness_requires_route_and_content_to_stabilize() -> None:
    readiness = evaluate_app_readiness(
        samples=[
            {"resolved_route": "/dashboard", "shell_ready": True, "content_ready": False},
            {"resolved_route": "/dashboard", "shell_ready": True, "content_ready": True},
            {"resolved_route": "/dashboard", "shell_ready": True, "content_ready": True},
        ]
    )

    assert readiness.shell_ready is True
    assert readiness.route_ready is True
    assert readiness.content_ready is True


def test_app_readiness_not_ready_when_samples_less_than_stabilization_window() -> None:
    readiness = evaluate_app_readiness(
        samples=[
            {"resolved_route": "/dashboard", "shell_ready": True, "content_ready": True},
            {"resolved_route": "/dashboard", "shell_ready": True, "content_ready": True},
        ],
        stabilization_window=3,
    )

    assert readiness.shell_ready is False
    assert readiness.route_ready is False
    assert readiness.content_ready is False


@pytest.mark.anyio
async def test_collect_route_signals_merges_snapshot_into_richer_route_hints() -> None:
    class FakeSession:
        async def collect_route_snapshot(self, *, crawl_scope: str):
            del crawl_scope
            return {"resolved_route": "/users", "route_source": "router"}

        async def collect_route_hints(self, *, crawl_scope: str):
            del crawl_scope
            return [
                {
                    "path": "/users",
                    "title": "用户管理",
                    "context_constraints": {"auth_scope": "admin"},
                }
            ]

    extractor = RuntimeRouteHintExtractor()
    signals = await extractor.collect_route_signals(browser_session=FakeSession(), crawl_scope="current")

    assert len(signals) == 1
    assert signals[0]["route_path"] == "/users"
    assert signals[0]["page_title"] == "用户管理"
    assert signals[0]["discovery_sources"] == ["runtime_route_hints", "runtime_route_snapshot"]
    assert signals[0]["context_constraints"] == {"auth_scope": "admin", "route_source": "router"}


@pytest.mark.anyio
async def test_collect_route_signals_uses_settled_snapshot_after_hints() -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.hints_collected = False

        async def collect_route_hints(self, *, crawl_scope: str):
            del crawl_scope
            self.hints_collected = True
            return [{"path": "/dashboard", "title": "仪表盘"}]

        async def collect_route_snapshot(self, *, crawl_scope: str):
            del crawl_scope
            if self.hints_collected:
                return {"resolved_route": "/dashboard", "route_source": "router"}
            return {"resolved_route": "/", "route_source": "pathname"}

    extractor = RuntimeRouteHintExtractor()
    signals = await extractor.collect_route_signals(browser_session=FakeSession(), crawl_scope="full")

    assert len(signals) == 1
    assert signals[0]["route_path"] == "/dashboard"
    assert signals[0]["discovery_sources"] == ["runtime_route_hints", "runtime_route_snapshot"]


@pytest.mark.anyio
async def test_collect_route_signals_degrades_snapshot_failure_and_preserves_hints() -> None:
    class FakeSession:
        async def collect_route_hints(self, *, crawl_scope: str):
            del crawl_scope
            return [{"path": "/users", "title": "用户管理"}]

        async def collect_route_snapshot(self, *, crawl_scope: str):
            del crawl_scope
            raise RuntimeError("snapshot unavailable")

    extractor = RuntimeRouteHintExtractor()
    signals = await extractor.collect_route_signals(browser_session=FakeSession(), crawl_scope="full")

    assert len(signals) == 1
    assert signals[0]["route_path"] == "/users"
    assert signals[0]["page_title"] == "用户管理"
    assert signals[0]["discovery_sources"] == ["runtime_route_hints"]


@pytest.mark.anyio
async def test_collect_route_signals_normalizes_trailing_slash_for_merging() -> None:
    class FakeSession:
        async def collect_route_hints(self, *, crawl_scope: str):
            del crawl_scope
            return [{"path": "/users/", "title": "用户管理"}]

        async def collect_route_snapshot(self, *, crawl_scope: str):
            del crawl_scope
            return {"resolved_route": "/users", "route_source": "router"}

    extractor = RuntimeRouteHintExtractor()
    signals = await extractor.collect_route_signals(browser_session=FakeSession(), crawl_scope="full")

    assert len(signals) == 1
    assert signals[0]["route_path"] == "/users"
    assert signals[0]["discovery_sources"] == ["runtime_route_hints", "runtime_route_snapshot"]


@pytest.mark.anyio
async def test_collect_route_signals_normalizes_query_fragment_for_merging() -> None:
    class FakeSession:
        async def collect_route_hints(self, *, crawl_scope: str):
            del crawl_scope
            return [{"path": "/users/?tab=all#x", "title": "用户管理"}]

        async def collect_route_snapshot(self, *, crawl_scope: str):
            del crawl_scope
            return {"resolved_route": "/users?source=snapshot#y", "route_source": "router"}

    extractor = RuntimeRouteHintExtractor()
    signals = await extractor.collect_route_signals(browser_session=FakeSession(), crawl_scope="full")

    assert len(signals) == 1
    assert signals[0]["route_path"] == "/users"
    assert signals[0]["discovery_sources"] == ["runtime_route_hints", "runtime_route_snapshot"]
