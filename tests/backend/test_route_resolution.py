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
