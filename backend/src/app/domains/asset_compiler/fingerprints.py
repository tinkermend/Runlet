from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from app.shared.enums import AssetStatus


SAFE_MAX_DIFF_SCORE = 0.2
SUSPECT_MAX_DIFF_SCORE = 0.6

_DIFF_WEIGHTS = {
    "navigation_hash": 0.2,
    "key_locator_hash": 0.45,
    "semantic_summary_hash": 0.15,
    "structure_hash": 0.2,
}

_LEGACY_KEY_LOCATOR_HASH = "legacy_key_locator_hash"
_LEGACY_STRUCTURE_HASH = "legacy_structure_hash"


@dataclass(frozen=True)
class FingerprintDiff:
    score: float
    changed_components: set[str]
    status: AssetStatus


def build_page_fingerprint(page_payload: dict[str, object]) -> dict[str, str]:
    normalized_page = _normalize_page(page_payload.get("page"))
    normalized_menus = _normalize_menus(page_payload.get("menus"))
    normalized_elements = _normalize_elements(page_payload.get("elements"))
    legacy_elements = _legacy_elements_projection(normalized_elements)

    navigation_hash = _stable_hash(
        {
            "page": {
                "route_path": normalized_page["route_path"],
                "page_title": normalized_page["page_title"],
            },
            "menus": normalized_menus,
        }
    )
    key_locator_hash = _stable_hash(
        [
            {
                "element_type": element["element_type"],
                "element_role": element["element_role"],
                "state_signature": element["state_signature"],
                "locator_bundle_summary": element["locator_bundle_summary"],
                "attributes": element["attributes"],
            }
            for element in normalized_elements
        ]
    )
    legacy_key_locator_hash = _stable_hash(
        [
            {
                "element_type": element["element_type"],
                "element_role": element["element_role"],
                "playwright_locator": element["playwright_locator"],
                "attributes": element["attributes"],
            }
            for element in legacy_elements
        ]
    )
    semantic_summary_hash = _stable_hash(
        {
            "page_title": normalized_page["page_title"],
            "page_summary": normalized_page["page_summary"],
            "usage_descriptions": [element["usage_description"] for element in normalized_elements],
            "texts": [element["element_text"] for element in normalized_elements],
        }
    )
    structure_hash = _stable_hash(
        {
            "page": normalized_page,
            "menus": normalized_menus,
            "elements": normalized_elements,
        }
    )
    legacy_structure_hash = _stable_hash(
        {
            "page": normalized_page,
            "menus": normalized_menus,
            "elements": legacy_elements,
        }
    )

    return {
        "navigation_hash": navigation_hash,
        "key_locator_hash": key_locator_hash,
        "semantic_summary_hash": semantic_summary_hash,
        "structure_hash": structure_hash,
        _LEGACY_KEY_LOCATOR_HASH: legacy_key_locator_hash,
        _LEGACY_STRUCTURE_HASH: legacy_structure_hash,
    }


def compare_fingerprints(
    old_fingerprint: dict[str, str] | None,
    new_fingerprint: dict[str, str],
) -> FingerprintDiff:
    if not old_fingerprint:
        return FingerprintDiff(score=0.0, changed_components=set(), status=AssetStatus.SAFE)

    changed_components = {
        component
        for component in _DIFF_WEIGHTS
        if _component_changed(
            component=component,
            old_fingerprint=old_fingerprint,
            new_fingerprint=new_fingerprint,
        )
    }
    score = sum(_DIFF_WEIGHTS[component] for component in changed_components)
    return FingerprintDiff(
        score=round(score, 4),
        changed_components=changed_components,
        status=map_diff_score_to_status(score),
    )


def map_diff_score_to_status(score: float) -> AssetStatus:
    if score <= SAFE_MAX_DIFF_SCORE:
        return AssetStatus.SAFE
    if score <= SUSPECT_MAX_DIFF_SCORE:
        return AssetStatus.SUSPECT
    return AssetStatus.STALE


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_page(page: object) -> dict[str, str]:
    payload = page if isinstance(page, dict) else {}
    return {
        "route_path": _clean_text(payload.get("route_path")),
        "page_title": _clean_text(payload.get("page_title")),
        "page_summary": _clean_text(payload.get("page_summary")),
    }


def _normalize_menus(menus: object) -> list[dict[str, object]]:
    if not isinstance(menus, list):
        return []

    normalized = []
    for item in menus:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "label": _clean_text(item.get("label")),
                "route_path": _clean_text(item.get("route_path")),
                "depth": _clean_int(item.get("depth")),
                "sort_order": _clean_int(item.get("sort_order")),
            }
        )

    return sorted(
        normalized,
        key=lambda item: (
            item["depth"],
            item["sort_order"],
            item["label"],
            item["route_path"],
        ),
    )


def _normalize_elements(elements: object) -> list[dict[str, object]]:
    if not isinstance(elements, list):
        return []

    normalized = []
    for item in elements:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "element_type": _clean_text(item.get("element_type")),
                "element_role": _clean_text(item.get("element_role")),
                "element_text": _clean_text(item.get("element_text")),
                "playwright_locator": _clean_text(item.get("playwright_locator")),
                "state_signature": _clean_text(item.get("state_signature")),
                "usage_description": _clean_text(item.get("usage_description")),
                "attributes": _normalize_attributes(item.get("attributes")),
                "locator_bundle_summary": _normalize_locator_bundle_summary(item.get("locator_bundle")),
            }
        )

    return sorted(
        normalized,
        key=lambda item: (
            item["element_type"],
            item["element_role"],
            item["element_text"],
            item["state_signature"],
            _stable_hash(item["locator_bundle_summary"]),
        ),
    )


def _legacy_elements_projection(elements: list[dict[str, object]]) -> list[dict[str, object]]:
    legacy_elements = [
        {
            "element_type": element["element_type"],
            "element_role": element["element_role"],
            "element_text": element["element_text"],
            "playwright_locator": element["playwright_locator"],
            "usage_description": element["usage_description"],
            "attributes": element["attributes"],
        }
        for element in elements
    ]
    return sorted(
        legacy_elements,
        key=lambda item: (
            item["element_type"],
            item["element_role"],
            item["element_text"],
            item["playwright_locator"],
        ),
    )


def _normalize_locator_bundle_summary(value: object) -> dict[str, object]:
    bundle = value if isinstance(value, dict) else {}
    candidates = bundle.get("candidates")
    if not isinstance(candidates, list):
        return {"candidate_count": 0, "strategies": [], "selectors": []}

    normalized_candidates = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        strategy_type = _clean_text(item.get("strategy_type"))
        selector = _clean_text(item.get("selector"))
        if not strategy_type and not selector:
            continue
        normalized_candidates.append(
            {
                "strategy_type": strategy_type,
                "selector": selector,
            }
        )

    return {
        "candidate_count": len(normalized_candidates),
        "strategies": [item["strategy_type"] for item in normalized_candidates],
        "selectors": [item["selector"] for item in normalized_candidates],
    }


def _normalize_attributes(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): value[key] for key in sorted(value)}


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _clean_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    return 0


def _component_changed(
    *,
    component: str,
    old_fingerprint: dict[str, str],
    new_fingerprint: dict[str, str],
) -> bool:
    old_value = _clean_text(old_fingerprint.get(component))
    if old_value == _clean_text(new_fingerprint.get(component)):
        return False
    legacy_field = _legacy_field_for_component(component)
    if legacy_field and old_value == _clean_text(new_fingerprint.get(legacy_field)):
        return False
    return True


def _legacy_field_for_component(component: str) -> str | None:
    if component == "key_locator_hash":
        return _LEGACY_KEY_LOCATOR_HASH
    if component == "structure_hash":
        return _LEGACY_STRUCTURE_HASH
    return None
