from enum import StrEnum


class AssetStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    SUSPECT = "suspect"
    STALE = "stale"
    DISABLED = "disabled"
