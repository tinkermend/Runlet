from __future__ import annotations

from typing import Iterable

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


def _contains_transient_pattern(haystack: str, patterns: Iterable[str]) -> bool:
    haystack_lower = haystack.lower()
    return any(pattern in haystack_lower for pattern in patterns)


def is_retryable_failure(*, failure_category: str | None, error_message: str | None) -> bool:
    if failure_category and failure_category in RETRYABLE_FAILURE_CATEGORIES:
        return True
    if failure_category and failure_category in NON_RETRYABLE_STEP_FAILURES:
        return False
    if error_message and _contains_transient_pattern(error_message, TRANSIENT_ERROR_PATTERNS):
        return True
    return False
