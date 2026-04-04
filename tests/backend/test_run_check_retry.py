from app.jobs.run_check_retry import is_retryable_failure


def test_is_retryable_failure_accepts_navigation_and_page_ready():
    assert is_retryable_failure(failure_category="navigation_failed", error_message=None) is True
    assert is_retryable_failure(failure_category="page_not_ready", error_message=None) is True


def test_is_retryable_failure_rejects_assertion_and_auth_blocked():
    assert is_retryable_failure(failure_category="assertion_failed", error_message=None) is False
    assert is_retryable_failure(failure_category="auth_blocked", error_message=None) is False
