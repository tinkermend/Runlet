from app.jobs.run_check_retry import is_retryable_failure


def test_is_retryable_failure_accepts_navigation_and_page_ready():
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
