from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.infrastructure.db.models.crawl import MenuNode, Page, PageElement

QUALITY_GATE_MIN_SCORE = 0.7
ACTIVE_PAGE_COUNT_COLLAPSE_RATIO = 0.5


@dataclass(frozen=True)
class RetirementDecision:
    page_asset_id: UUID
    page_check_ids: list[UUID]
    reason: str


@dataclass(frozen=True)
class QualityGateDecision:
    allow_retirement: bool
    warning_payload: dict[str, object] | None = None


@dataclass(frozen=True)
class ActivePageTruth:
    page_asset_id: UUID
    route_path: str


@dataclass(frozen=True)
class ActiveCheckTruth:
    page_check_id: UUID
    page_asset_id: UUID
    blocking_dependency_json: dict[str, object]


@dataclass(frozen=True)
class SnapshotTruth:
    route_paths: set[str]
    menu_chain_by_route: dict[str, list[str]]
    elements_by_route: dict[str, list[dict[str, str]]]


def evaluate_retirement_quality_gate(
    *,
    crawl_type: str,
    degraded: bool,
    quality_score: float | None,
    current_page_count: int,
    previous_active_page_count: int,
) -> QualityGateDecision:
    if crawl_type != "full":
        return QualityGateDecision(allow_retirement=False)
    if degraded:
        return QualityGateDecision(allow_retirement=False)
    if quality_score is None or quality_score < QUALITY_GATE_MIN_SCORE:
        return QualityGateDecision(allow_retirement=False)
    if previous_active_page_count <= 0:
        return QualityGateDecision(allow_retirement=True)

    collapse_ratio = current_page_count / previous_active_page_count
    if collapse_ratio < ACTIVE_PAGE_COUNT_COLLAPSE_RATIO:
        return QualityGateDecision(
            allow_retirement=False,
            warning_payload={
                "reason": "page_count_collapse",
                "current_page_count": current_page_count,
                "previous_active_page_count": previous_active_page_count,
                "collapse_ratio": round(collapse_ratio, 4),
                "collapse_ratio_threshold": ACTIVE_PAGE_COUNT_COLLAPSE_RATIO,
            },
        )
    return QualityGateDecision(allow_retirement=True)


def build_current_snapshot_truth(
    *,
    pages: list[Page],
    menus: list[MenuNode],
    elements: list[PageElement],
) -> SnapshotTruth:
    page_route_by_id = {page.id: _normalize_text(page.route_path) for page in pages}
    route_paths = {route_path for route_path in page_route_by_id.values() if route_path}

    menu_chain_by_route: dict[str, list[str]] = {}
    menus_sorted = sorted(
        menus,
        key=lambda row: (row.page_id, row.depth, row.sort_order, str(row.id)),
    )
    for menu in menus_sorted:
        route_path = page_route_by_id.get(menu.page_id, "")
        if not route_path:
            continue
        label = _normalize_text(menu.label)
        if not label:
            continue
        menu_chain_by_route.setdefault(route_path, []).append(label)

    elements_by_route: dict[str, list[dict[str, str]]] = {}
    for element in elements:
        route_path = page_route_by_id.get(element.page_id, "")
        if not route_path:
            continue
        elements_by_route.setdefault(route_path, []).append(
            {
                "kind": _normalize_text(element.element_type),
                "role": _normalize_text(element.element_role),
                "text": _normalize_text(element.element_text),
            }
        )

    return SnapshotTruth(
        route_paths=route_paths,
        menu_chain_by_route=menu_chain_by_route,
        elements_by_route=elements_by_route,
    )


def build_blocking_dependency_json(
    *,
    steps_json: list[dict[str, object]] | None,
    assertion_schema: dict[str, object] | None,
) -> dict[str, object]:
    menu_chain: list[str] = []
    required_elements: list[dict[str, str]] = []
    derived_required_elements: list[dict[str, str]] = []

    for step in steps_json or []:
        if not isinstance(step, dict):
            continue
        module_name = _normalize_text(step.get("module"))
        params = step.get("params")
        if module_name == "nav.menu_chain" and isinstance(params, dict):
            menu_chain = [
                _normalize_text(label)
                for label in params.get("menu_chain", [])
                if _normalize_text(label)
            ]
        if module_name == "assert.table_visible":
            derived_required_elements.append({"kind": "table", "role": "table"})

    if isinstance(assertion_schema, dict):
        assertion_name = _normalize_text(assertion_schema.get("assertion"))
        if assertion_name == "table_visible":
            derived_required_elements.append({"kind": "table", "role": "table"})
        if assertion_name == "modal_visible":
            derived_required_elements.append({"kind": "dialog", "role": "dialog"})

        for item in assertion_schema.get("required_elements", []):
            if not isinstance(item, dict):
                continue
            normalized = {
                "kind": _normalize_text(item.get("kind")),
                "role": _normalize_text(item.get("role")),
                "text": _normalize_text(item.get("text")),
            }
            compacted = {key: value for key, value in normalized.items() if value}
            if compacted:
                required_elements.append(compacted)
    required_elements.extend(derived_required_elements)

    deduped_required_elements: list[dict[str, str]] = []
    seen = set()
    for element in required_elements:
        signature = tuple(sorted(element.items()))
        if signature in seen:
            continue
        seen.add(signature)
        deduped_required_elements.append(element)

    return {
        "menu_chain": menu_chain,
        "required_elements": deduped_required_elements,
    }


def reconcile_retirement_decisions(
    *,
    active_pages: list[ActivePageTruth],
    active_checks: list[ActiveCheckTruth],
    snapshot_truth: SnapshotTruth,
    quality_gate: QualityGateDecision,
) -> list[RetirementDecision]:
    if not quality_gate.allow_retirement:
        return []

    decisions: list[RetirementDecision] = []
    route_path_by_asset_id = {row.page_asset_id: row.route_path for row in active_pages}
    checks_by_asset_id: dict[UUID, list[UUID]] = {}
    for row in active_checks:
        checks_by_asset_id.setdefault(row.page_asset_id, []).append(row.page_check_id)

    missing_asset_ids = [
        row.page_asset_id
        for row in active_pages
        if row.route_path and row.route_path not in snapshot_truth.route_paths
    ]
    for page_asset_id in missing_asset_ids:
        decisions.append(
            RetirementDecision(
                page_asset_id=page_asset_id,
                page_check_ids=checks_by_asset_id.get(page_asset_id, []),
                reason="missing_page",
            )
        )

    missing_assets = set(missing_asset_ids)
    check_groups: dict[tuple[UUID, str], list[UUID]] = {}
    for row in active_checks:
        if row.page_asset_id in missing_assets:
            continue
        route_path = route_path_by_asset_id.get(row.page_asset_id, "")
        if not route_path or route_path not in snapshot_truth.route_paths:
            continue

        dependencies = _normalize_dependency_json(row.blocking_dependency_json)
        menu_chain = dependencies["menu_chain"]
        required_elements = dependencies["required_elements"]
        current_menu_chain = snapshot_truth.menu_chain_by_route.get(route_path, [])
        current_elements = snapshot_truth.elements_by_route.get(route_path, [])

        reason: str | None = None
        if menu_chain and not _menu_chain_satisfied(expected=menu_chain, current=current_menu_chain):
            reason = "missing_menu_chain"
        elif required_elements and not _required_elements_satisfied(
            expected=required_elements,
            current=current_elements,
        ):
            reason = "missing_key_element"

        if reason is None:
            continue
        check_groups.setdefault((row.page_asset_id, reason), []).append(row.page_check_id)

    for (page_asset_id, reason), check_ids in check_groups.items():
        decisions.append(
            RetirementDecision(
                page_asset_id=page_asset_id,
                page_check_ids=sorted(set(check_ids), key=str),
                reason=reason,
            )
        )
    return decisions


def _normalize_dependency_json(value: dict[str, object] | None) -> dict[str, list[dict[str, str]] | list[str]]:
    menu_chain = []
    required_elements: list[dict[str, str]] = []

    if isinstance(value, dict):
        menu_chain = [
            _normalize_text(label)
            for label in value.get("menu_chain", [])
            if _normalize_text(label)
        ]
        for item in value.get("required_elements", []):
            if not isinstance(item, dict):
                continue
            normalized = {
                "kind": _normalize_text(item.get("kind")),
                "role": _normalize_text(item.get("role")),
                "text": _normalize_text(item.get("text")),
            }
            compacted = {key: value for key, value in normalized.items() if value}
            if compacted:
                required_elements.append(compacted)

    return {
        "menu_chain": menu_chain,
        "required_elements": required_elements,
    }


def _menu_chain_satisfied(*, expected: list[str], current: list[str]) -> bool:
    if not expected:
        return True
    if not current:
        return False
    index = 0
    for label in current:
        if label == expected[index]:
            index += 1
            if index == len(expected):
                return True
    return False


def _required_elements_satisfied(
    *,
    expected: list[dict[str, str]],
    current: list[dict[str, str]],
) -> bool:
    for descriptor in expected:
        if not any(_element_matches(descriptor=descriptor, current=row) for row in current):
            return False
    return True


def _element_matches(*, descriptor: dict[str, str], current: dict[str, str]) -> bool:
    for key in ("kind", "role", "text"):
        expected = _normalize_text(descriptor.get(key))
        if expected and _normalize_text(current.get(key)) != expected:
            return False
    return True


def _normalize_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
