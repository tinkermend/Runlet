from enum import StrEnum


class AssetStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    SUSPECT = "suspect"
    STALE = "stale"
    DISABLED = "disabled"


class AuthStateStatus(StrEnum):
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"
    EXPIRED = "expired"


class QueuedJobStatus(StrEnum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYABLE_FAILED = "retryable_failed"
    SKIPPED = "skipped"
