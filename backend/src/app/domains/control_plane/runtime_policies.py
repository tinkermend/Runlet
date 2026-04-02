from __future__ import annotations

from dataclasses import dataclass

from apscheduler.triggers.cron import CronTrigger

from app.shared.enums import RuntimePolicyState


class InvalidRuntimePolicyScheduleError(ValueError):
    pass


@dataclass(frozen=True)
class UpsertSystemAuthPolicy:
    enabled: bool
    schedule_expr: str
    auth_mode: str
    captcha_provider: str = "ddddocr"


@dataclass(frozen=True)
class UpsertSystemCrawlPolicy:
    enabled: bool
    schedule_expr: str
    crawl_scope: str = "full"


def validate_policy_schedule_expr(schedule_expr: str) -> None:
    try:
        CronTrigger.from_crontab(schedule_expr, timezone="UTC")
    except ValueError as exc:
        raise InvalidRuntimePolicyScheduleError(
            f"invalid schedule expression: {schedule_expr}"
        ) from exc


def resolve_runtime_policy_state(*, enabled: bool) -> str:
    if enabled:
        return RuntimePolicyState.ACTIVE.value
    return RuntimePolicyState.PAUSED.value


def is_policy_effectively_active(*, enabled: bool, state: str) -> bool:
    return enabled and state == RuntimePolicyState.ACTIVE.value
