from __future__ import annotations

from enum import StrEnum


class FailureCategory(StrEnum):
    SYSTEM_NOT_FOUND = "system_not_found"
    PAGE_OR_MENU_NOT_RESOLVED = "page_or_menu_not_resolved"
    ELEMENT_ASSET_MISSING = "element_asset_missing"
    AUTH_BLOCKED = "auth_blocked"
    NAVIGATION_FAILED = "navigation_failed"
    PAGE_NOT_READY = "page_not_ready"
    ASSERTION_FAILED = "assertion_failed"
    RUNTIME_ERROR = "runtime_error"
