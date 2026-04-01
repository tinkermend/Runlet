from enum import StrEnum


class AssetStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    DEPRECATED = "deprecated"
