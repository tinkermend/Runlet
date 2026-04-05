from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

_DISCOVERY_SOURCE_PRIORITY = {
    "runtime_route_hints": 0,
    "dom_menu_tree": 1,
    "network_route_config": 2,
    "network_resource": 3,
    "network_request": 4,
    "reachability_probe": 5,
}


@dataclass(slots=True)
class NavigationTarget:
    target_kind: str
    route_hint: str | None
    locator_candidates: list[dict[str, object]] = field(default_factory=list)
    state_context: dict[str, object] = field(default_factory=dict)
    parent_target_key: str | None = None
    discovery_source: str | None = None
    safety_level: str = "readonly"
    materialization_status: str = "discovered"
    rejection_reason: str | None = None
    rejection_detail: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.target_kind = _normalize_text(self.target_kind) or "unknown"
        self.route_hint = _normalize_route(self.route_hint)
        self.parent_target_key = _normalize_text(self.parent_target_key)
        self.discovery_source = _normalize_text(self.discovery_source)
        self.safety_level = _normalize_text(self.safety_level) or "readonly"
        self.materialization_status = _normalize_text(self.materialization_status) or "discovered"
        self.rejection_reason = _normalize_text(self.rejection_reason)
        self.rejection_detail = _normalize_text(self.rejection_detail)
        self.state_context = _normalize_state_context(self.state_context)
        self.locator_candidates = _normalize_locator_candidates(self.locator_candidates)
        self.metadata = _normalize_metadata(self.metadata)

    @property
    def target_key(self) -> str:
        if self.target_kind == "page_route" and self.route_hint is not None:
            return f"page:{self.route_hint}"
        return self.dedupe_key()

    def dedupe_key(self) -> str:
        return json.dumps(
            {
                "target_kind": self.target_kind,
                "route_hint": self.route_hint,
                "state_context": self.state_context,
                "parent_target_key": self.parent_target_key,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def mark_queued(self) -> None:
        self.materialization_status = "queued"
        self.rejection_reason = None
        self.rejection_detail = None

    def mark_applied(self) -> None:
        self.materialization_status = "applied"
        self.rejection_reason = None
        self.rejection_detail = None

    def mark_duplicate(self, reason: str = "duplicate_target") -> None:
        self.materialization_status = "duplicate"
        self.rejection_reason = reason
        self.rejection_detail = None

    def mark_blocked(self, reason: str) -> None:
        self.materialization_status = "blocked"
        self.rejection_reason = reason
        self.rejection_detail = None

    def mark_not_applied(
        self,
        reason: str = "state_transition_not_applied",
        *,
        detail: str | None = None,
    ) -> None:
        self.materialization_status = "not_applied"
        self.rejection_reason = reason
        self.rejection_detail = _normalize_text(detail)

    def merge_from(self, other: "NavigationTarget") -> None:
        self.locator_candidates = _merge_locator_candidates(self.locator_candidates, other.locator_candidates)
        self.discovery_source = _prefer_discovery_source(self.discovery_source, other.discovery_source)
        self.metadata = _merge_metadata(self.metadata, other.metadata)

    def to_record(self) -> dict[str, object]:
        return {
            "target_key": self.target_key,
            "target_kind": self.target_kind,
            "route_hint": self.route_hint,
            "locator_candidates": [dict(candidate) for candidate in self.locator_candidates],
            "state_context": dict(self.state_context),
            "parent_target_key": self.parent_target_key,
            "discovery_source": self.discovery_source,
            "safety_level": self.safety_level,
            "materialization_status": self.materialization_status,
            "rejection_reason": self.rejection_reason,
            "rejection_detail": self.rejection_detail,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class NavigationTargetDecision:
    accepted: bool
    target: NavigationTarget
    reason: str | None = None


class NavigationTargetRegistry:
    def __init__(
        self,
        *,
        max_total_targets: int = 128,
        max_targets_per_route: int = 16,
        max_targets_per_kind: int = 64,
        max_children_per_parent: int = 32,
    ) -> None:
        self.max_total_targets = max(1, max_total_targets)
        self.max_targets_per_route = max(1, max_targets_per_route)
        self.max_targets_per_kind = max(1, max_targets_per_kind)
        self.max_children_per_parent = max(1, max_children_per_parent)

        self._targets: list[NavigationTarget] = []
        self._rejected_targets: list[NavigationTarget] = []
        self._targets_by_key: dict[str, NavigationTarget] = {}
        self._targets_by_route: dict[str, int] = {}
        self._targets_by_kind: dict[str, int] = {}
        self._targets_by_parent: dict[str, int] = {}

    @property
    def targets(self) -> list[NavigationTarget]:
        return list(self._targets)

    @property
    def rejected_targets(self) -> list[NavigationTarget]:
        return list(self._rejected_targets)

    def get_by_dedupe_key(self, dedupe_key: str) -> NavigationTarget | None:
        return self._targets_by_key.get(dedupe_key)

    def add(self, target: NavigationTarget) -> NavigationTargetDecision:
        dedupe_key = target.dedupe_key()
        existing = self._targets_by_key.get(dedupe_key)
        if existing is not None:
            existing.merge_from(target)
            target.mark_duplicate()
            self._rejected_targets.append(target)
            return NavigationTargetDecision(accepted=False, target=target, reason="duplicate_target")

        rejection_reason = self._budget_rejection_reason(target)
        if rejection_reason is not None:
            target.mark_blocked(rejection_reason)
            self._rejected_targets.append(target)
            return NavigationTargetDecision(accepted=False, target=target, reason=rejection_reason)

        target.mark_queued()
        self._targets.append(target)
        self._targets_by_key[dedupe_key] = target
        if target.route_hint is not None:
            self._targets_by_route[target.route_hint] = self._targets_by_route.get(target.route_hint, 0) + 1
        self._targets_by_kind[target.target_kind] = self._targets_by_kind.get(target.target_kind, 0) + 1
        if target.parent_target_key is not None:
            self._targets_by_parent[target.parent_target_key] = (
                self._targets_by_parent.get(target.parent_target_key, 0) + 1
            )
        return NavigationTargetDecision(accepted=True, target=target)

    def extend(self, targets: list[NavigationTarget]) -> list[NavigationTarget]:
        accepted_targets: list[NavigationTarget] = []
        for target in targets:
            decision = self.add(target)
            if decision.accepted:
                accepted_targets.append(decision.target)
        return accepted_targets

    def _budget_rejection_reason(self, target: NavigationTarget) -> str | None:
        if len(self._targets) >= self.max_total_targets:
            return "total_budget_exhausted"
        if target.route_hint is not None and self._targets_by_route.get(target.route_hint, 0) >= self.max_targets_per_route:
            return "route_budget_exhausted"
        if self._targets_by_kind.get(target.target_kind, 0) >= self.max_targets_per_kind:
            return "kind_budget_exhausted"
        if (
            target.parent_target_key is not None
            and self._targets_by_parent.get(target.parent_target_key, 0) >= self.max_children_per_parent
        ):
            return "parent_budget_exhausted"
        return None


def _normalize_route(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    route = value.strip()
    if not route or not route.startswith("/"):
        return None
    normalized = route.split("?", 1)[0].split("#", 1)[0]
    return normalized.rstrip("/") or "/"


def _normalize_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _normalize_state_context(value: Any) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    state_context: dict[str, object] = {}
    for raw_key, raw_value in value.items():
        key = _normalize_text(raw_key)
        if key is None:
            continue
        if isinstance(raw_value, str):
            cleaned = raw_value.strip()
            if cleaned:
                state_context[key] = cleaned
        elif isinstance(raw_value, (int, float, bool)):
            state_context[key] = raw_value
    return state_context


def _normalize_locator_candidates(value: Any) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, object]] = []
    seen: set[str] = set()
    for candidate in value:
        if not isinstance(candidate, dict):
            continue
        strategy_type = _normalize_text(candidate.get("strategy_type"))
        selector = _normalize_text(candidate.get("selector"))
        if strategy_type is None or selector is None:
            continue
        serialized = json.dumps(
            {"strategy_type": strategy_type, "selector": selector},
            ensure_ascii=False,
            sort_keys=True,
        )
        if serialized in seen:
            continue
        seen.add(serialized)
        normalized.append({"strategy_type": strategy_type, "selector": selector})
    return normalized


def _merge_locator_candidates(
    existing: list[dict[str, object]],
    incoming: list[dict[str, object]],
) -> list[dict[str, object]]:
    return _normalize_locator_candidates([*existing, *incoming])


def _normalize_metadata(value: Any) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    metadata: dict[str, object] = {}
    for key, raw_value in value.items():
        normalized_key = _normalize_text(key)
        if normalized_key is None:
            continue
        if isinstance(raw_value, dict):
            nested = _normalize_metadata(raw_value)
            if nested:
                metadata[normalized_key] = nested
        elif isinstance(raw_value, list):
            items = [item for item in raw_value if isinstance(item, (str, int, float, bool, dict))]
            if items:
                metadata[normalized_key] = items
        elif isinstance(raw_value, (str, int, float, bool)):
            if isinstance(raw_value, str):
                cleaned = raw_value.strip()
                if cleaned:
                    metadata[normalized_key] = cleaned
            else:
                metadata[normalized_key] = raw_value
    return metadata


def _merge_metadata(existing: dict[str, object], incoming: dict[str, object]) -> dict[str, object]:
    merged = dict(existing)
    for key, raw_value in incoming.items():
        existing_value = merged.get(key)
        if isinstance(existing_value, dict) and isinstance(raw_value, dict):
            merged[key] = _merge_metadata(existing_value, raw_value)
            continue
        if isinstance(existing_value, list) and isinstance(raw_value, list):
            seen: set[str] = set()
            merged_items: list[object] = []
            for item in [*existing_value, *raw_value]:
                serialized = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
                if serialized in seen:
                    continue
                seen.add(serialized)
                merged_items.append(item)
            merged[key] = merged_items
            continue
        if existing_value in (None, "", [], {}):
            merged[key] = raw_value
    return merged


def _prefer_discovery_source(existing: str | None, incoming: str | None) -> str | None:
    if existing is None:
        return incoming
    if incoming is None:
        return existing

    existing_priority = _DISCOVERY_SOURCE_PRIORITY.get(existing, 100)
    incoming_priority = _DISCOVERY_SOURCE_PRIORITY.get(incoming, 100)
    if incoming_priority < existing_priority:
        return incoming
    if incoming_priority > existing_priority:
        return existing
    return min(existing, incoming)
