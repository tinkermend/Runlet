from app.jobs.run_check_retry import is_retryable_failure


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


def test_is_retryable_failure_allows_runtime_error_with_timeout_like_message():
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
