from enum import StrEnum


class AssetStatus(StrEnum):
    SAFE = "safe"
    SUSPECT = "suspect"
    STALE = "stale"


class AssetCompileStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


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


class ExecutionResultStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class RenderResultStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class PublishedJobState(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class RuntimePolicyState(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"


class RuntimeTriggerSource(StrEnum):
    SCHEDULER = "scheduler"
    MANUAL = "manual"
    PLATFORM = "platform"


class CrawlScope(StrEnum):
    FULL = "full"
    INCREMENTAL = "incremental"
