from __future__ import annotations

import re

from app.domains.asset_compiler.schemas import LocatorBundle


STRATEGY_PRIORITY = {
    "semantic": 100,
    "label": 90,
    "testid": 80,
    "text_anchor": 70,
    "structure": 60,
    "css": 10,
}

_HASH_CLASS_RE = re.compile(r"\.[A-Za-z_-]*[0-9a-f]{6,}[A-Za-z0-9_-]*")
_DYNAMIC_ID_RE = re.compile(r"#[A-Za-z_-]*\d{4,}[A-Za-z0-9_-]*")
_PURE_NTH_CHILD_RE = re.compile(r"^(?:[A-Za-z0-9_-]+\s*>\s*)*[A-Za-z0-9_-]+:nth-child\(\d+\)$")


def build_locator_bundle(
    *,
    locator_candidates: list[dict[str, object]] | None,
    state_context: dict[str, object] | None,
) -> LocatorBundle:
    filtered = [
        candidate
        for candidate in (locator_candidates or [])
        if not _is_forbidden_locator(candidate)
    ]
    ranked = sorted(filtered, key=_rank_locator_candidate, reverse=True)
    context = state_context or {}
    normalized_candidates = [
        {
            "strategy_type": _clean_text(candidate.get("strategy_type")),
            "selector": _clean_text(candidate.get("selector")),
            "context_constraints": dict(context),
            "stability_score": _clean_float(candidate.get("stability_score"), default=0.0),
            "specificity_score": _clean_float(candidate.get("specificity_score"), default=0.0),
            "observed_success_count": _clean_int(candidate.get("observed_success_count")),
            "fallback_rank": index + 1,
        }
        for index, candidate in enumerate(ranked)
    ]
    return LocatorBundle(candidates=normalized_candidates)


def _rank_locator_candidate(candidate: dict[str, object]) -> float:
    strategy_type = _clean_text(candidate.get("strategy_type")).lower()
    base = float(STRATEGY_PRIORITY.get(strategy_type, 0))
    stability = _clean_float(candidate.get("stability_score"), default=0.0)
    specificity = _clean_float(candidate.get("specificity_score"), default=0.0)
    observed_success_count = _clean_int(candidate.get("observed_success_count"))
    return base + stability + specificity + min(observed_success_count, 50) * 0.01


def _is_forbidden_locator(candidate: dict[str, object]) -> bool:
    selector = _clean_text(candidate.get("selector"))
    if not selector:
        return True
    selector_lower = selector.lower()

    if _DYNAMIC_ID_RE.search(selector):
        return True
    if _PURE_NTH_CHILD_RE.fullmatch(selector_lower):
        return True
    if _is_overlong_class_chain(selector):
        return True
    if _HASH_CLASS_RE.search(selector):
        return True
    return False


def _is_overlong_class_chain(selector: str) -> bool:
    class_chain_count = len(re.findall(r"\.[A-Za-z0-9_-]+", selector))
    return class_chain_count >= 6


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _clean_float(value: object, *, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return float(value)
    return default


def _clean_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    return 0
