from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RouteSnapshot:
    resolved_route: str
    route_source: str
    pathname: str | None
    hash_route: str | None
    router_route: str | None
    history_route: str | None


def normalize_route(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    route = value.strip()
    if not route or not route.startswith("/"):
        return None
    return route.rstrip("/") or "/"


def extract_hash_route(location_hash: object) -> str | None:
    if not isinstance(location_hash, str):
        return None
    raw_hash = location_hash.strip()
    if not raw_hash:
        return None
    if raw_hash.startswith("#!/"):
        return normalize_route(raw_hash[2:])
    if raw_hash.startswith("#"):
        return normalize_route(raw_hash[1:])
    return None


def resolve_route_snapshot(
    *,
    pathname: object,
    location_hash: object,
    router_route: object,
    history_route: object,
) -> RouteSnapshot:
    normalized_pathname = normalize_route(pathname)
    normalized_hash = extract_hash_route(location_hash)
    normalized_router = normalize_route(router_route)
    normalized_history = normalize_route(history_route)

    for source, candidate in (
        ("router", normalized_router),
        ("hash", normalized_hash),
        ("history", normalized_history),
        ("pathname", normalized_pathname),
    ):
        if candidate is not None:
            return RouteSnapshot(
                resolved_route=candidate,
                route_source=source,
                pathname=normalized_pathname,
                hash_route=normalized_hash,
                router_route=normalized_router,
                history_route=normalized_history,
            )

    return RouteSnapshot(
        resolved_route="/",
        route_source="fallback",
        pathname="/",
        hash_route=None,
        router_route=None,
        history_route=None,
    )
