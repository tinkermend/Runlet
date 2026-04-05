from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AppReadiness:
    shell_ready: bool
    route_ready: bool
    content_ready: bool


def evaluate_app_readiness(
    *,
    samples: list[dict[str, object]],
    stabilization_window: int = 2,
) -> AppReadiness:
    if not samples:
        return AppReadiness(shell_ready=False, route_ready=False, content_ready=False)

    window = max(1, stabilization_window)
    if len(samples) < window:
        return AppReadiness(shell_ready=False, route_ready=False, content_ready=False)

    tail = samples[-window:]

    shell_ready = bool(tail) and all(sample.get("shell_ready") is True for sample in tail)
    resolved_routes = [sample.get("resolved_route") for sample in tail]
    route_ready = bool(resolved_routes) and all(isinstance(route, str) and route for route in resolved_routes)
    if route_ready:
        route_ready = len(set(resolved_routes)) == 1
    content_ready = bool(tail) and all(sample.get("content_ready") is True for sample in tail)

    return AppReadiness(
        shell_ready=shell_ready,
        route_ready=route_ready,
        content_ready=content_ready,
    )
