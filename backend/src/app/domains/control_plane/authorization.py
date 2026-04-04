from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException


@dataclass(frozen=True)
class Principal:
    channel: str
    subject_type: str
    subject_id: str
    user_id: UUID | None = None


_ALLOWED_ACTIONS_BY_CHANNEL: dict[str, set[str]] = {
    "skills": {
        "create_check_request",
        "create_or_update_published_job",
    },
    "web_console": {
        "create_check_request",
        "create_or_update_published_job",
        "trigger_full_crawl",
        "trigger_incremental_crawl",
        "refresh_auth",
        "update_runtime_policy",
    },
    "cli": {
        "create_or_update_published_job",
        "trigger_full_crawl",
        "trigger_incremental_crawl",
        "refresh_auth",
    },
    "scheduler": {
        "trigger_published_job",
        "trigger_auth_policy",
        "trigger_crawl_policy",
    },
}


def authorize(*, principal: Principal, action: str, system_id: UUID | None) -> None:
    del system_id

    allowed_actions = _ALLOWED_ACTIONS_BY_CHANNEL.get(principal.channel, set())
    if action not in allowed_actions:
        raise HTTPException(status_code=403, detail="channel action not allowed")
