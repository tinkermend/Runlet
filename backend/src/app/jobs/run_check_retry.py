from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

RETRYABLE_FAILURE_CATEGORIES = {"navigation_failed", "page_not_ready"}
NON_RETRYABLE_STEP_FAILURES = {
    "context_mismatch",
    "ambiguous_match",
    "locator_all_failed",
    "element_became_hidden",
    "state_not_reached",
}
TRANSIENT_ERROR_PATTERNS = (
    "timeout",
    "net::",
    "connection reset",
    "target closed",
    "temporarily unavailable",
)


def _normalize_failure_category(failure_category: str | None) -> str | None:
    if not failure_category:
        return None
    return failure_category.strip().lower()


def _contains_transient_pattern(haystack: str, patterns: Iterable[str]) -> bool:
    haystack_lower = haystack.lower()
    return any(pattern in haystack_lower for pattern in patterns)


def is_retryable_failure(*, failure_category: str | None, error_message: str | None) -> bool:
    category = _normalize_failure_category(failure_category)
    if category and category in RETRYABLE_FAILURE_CATEGORIES:
        return True
    if category and category in NON_RETRYABLE_STEP_FAILURES:
        return False
    if (
        category == "runtime_error"
        and error_message
        and _contains_transient_pattern(error_message, TRANSIENT_ERROR_PATTERNS)
    ):
        return True
    return False


def compute_backoff_ms(*, attempt_no: int, base_backoff_ms: int, jitter_ms: int) -> int:
    multiplier = 2 ** max(attempt_no - 1, 0)
    backoff = base_backoff_ms * multiplier + jitter_ms
    return max(0, backoff)


def build_attempt_entry(
    *,
    attempt_no: int,
    started_at: datetime,
    finished_at: datetime,
    status: str,
    failure_category: str | None,
    retryable: bool,
    backoff_ms: int,
) -> dict[str, Any]:
    return {
        "attempt_no": attempt_no,
        "started_at": started_at,
        "finished_at": finished_at,
        "status": status,
        "failure_category": failure_category,
        "retryable": retryable,
        "backoff_ms": backoff_ms,
    }
