from datetime import datetime

from app.jobs.run_check_retry import (
    build_attempt_entry,
    compute_backoff_ms,
    is_retryable_failure,
 )


def test_is_retryable_failure_accepts_navigation_and_page_not_ready():
    assert is_retryable_failure(failure_category="navigation_failed", error_message=None) is True
    assert is_retryable_failure(failure_category="page_not_ready", error_message=None) is True


def test_is_retryable_failure_rejects_assertion_and_auth_blocked():
    assert is_retryable_failure(failure_category="assertion_failed", error_message=None) is False
    assert is_retryable_failure(failure_category="auth_blocked", error_message=None) is False


def test_is_retryable_failure_rejects_assertion_with_timeout_like_message():
    assert (
        is_retryable_failure(
            failure_category="assertion_failed",
            error_message="Timeout 30000ms net::ERR_CONNECTION_RESET",
        )
        is False
    )


def test_runtime_error_with_transient_message_is_retryable():
    assert (
        is_retryable_failure(
            failure_category="runtime_error", error_message="Timeout 30000ms exceeded"
        )
        is True
    )


def test_is_retryable_failure_normalizes_failure_category_input():
    assert is_retryable_failure(failure_category="  PAGE_NOT_READY  ", error_message=None) is True
    assert is_retryable_failure(failure_category="Navigation_Failed", error_message=None) is True


def test_is_retryable_failure_handles_blank_or_none_category_with_transient_message():
    assert (
        is_retryable_failure(failure_category="   ", error_message="Timed out due to timeout")
        is False
    )
    assert (
        is_retryable_failure(failure_category=None, error_message="Timeout 100ms")
        is False
    )


def test_non_retryable_step_failure_ignores_transient_message():
    assert (
        is_retryable_failure(
            failure_category="locator_all_failed",
            error_message="net::ERR_CONNECTION_RESET while trying to click",
        )
        is False
    )


def test_runtime_error_transient_text_supported():
    assert (
        is_retryable_failure(
            failure_category="runtime_error",
            error_message="Connection reset caused a temporary failure in runtime_error",
        )
        is True
    )


def test_compute_backoff_ms_doubles_per_attempt():
    assert compute_backoff_ms(attempt_no=1, base_backoff_ms=1000, jitter_ms=0) == 1000
    assert compute_backoff_ms(attempt_no=2, base_backoff_ms=1000, jitter_ms=0) == 2000
    assert compute_backoff_ms(attempt_no=3, base_backoff_ms=500, jitter_ms=100) == 2100


def test_build_attempt_entry_includes_required_fields():
    entry = build_attempt_entry(
        attempt_no=1,
        started_at=datetime.fromisoformat("2026-01-01T00:00:00"),
        finished_at=datetime.fromisoformat("2026-01-01T00:00:01"),
        status="failed",
        failure_category="navigation_failed",
        retryable=True,
        backoff_ms=1000,
    )
    assert entry["attempt_no"] == 1
    assert entry["retryable"] is True
    assert entry["backoff_ms"] == 1000

    assert entry["started_at"] == "2026-01-01T00:00:00"
    assert entry["finished_at"] == "2026-01-01T00:00:01"
    assert entry["status"] == "failed"
    assert entry["failure_category"] == "navigation_failed"
