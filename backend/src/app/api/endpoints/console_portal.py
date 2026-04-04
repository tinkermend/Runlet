from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Annotated
from fastapi import APIRouter, Depends
from sqlmodel import Session, func, select

from app.api.deps_auth import require_console_user
from app.domains.control_plane.console_schemas import (
    DashboardSummary,
    SystemCreateRequest,
    SystemCreated,
    SystemItem,
)
from app.infrastructure.db.console_session import get_console_db
from app.infrastructure.db.models.assets import PageAsset, PageCheck
from app.infrastructure.db.models.execution import ExecutionPlan, ExecutionRun
from app.infrastructure.db.models.identity import User
from app.infrastructure.db.models.systems import System

router = APIRouter(prefix="/portal", tags=["console-portal"])

ConsoleDep = Annotated[Session, Depends(get_console_db)]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _system_status(system: System) -> str:
    """Derive a simple status label for a system."""
    return "ready"


@router.get("/dashboard", response_model=DashboardSummary)
def get_dashboard(
    session: ConsoleDep,
    _: User = Depends(require_console_user),
) -> DashboardSummary:
    now = _utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = now - timedelta(hours=24)

    # today_runs: execution_runs created today
    today_runs = session.exec(
        select(func.count(ExecutionRun.id)).where(ExecutionRun.created_at >= today_start)
    ).one()

    # active_tasks: page_checks with lifecycle_status = 'active'
    active_tasks = session.exec(
        select(func.count(PageCheck.id)).where(PageCheck.lifecycle_status == "active")
    ).one()

    # systems_count
    systems_count = session.exec(select(func.count(System.id))).one()

    # recent_failures_24h
    recent_failures_24h = session.exec(
        select(func.count(ExecutionRun.id)).where(
            ExecutionRun.status == "failed",
            ExecutionRun.created_at >= yesterday,
        )
    ).one()

    # recent_exceptions: last 5 failed runs with context
    failed_runs = session.exec(
        select(ExecutionRun)
        .where(ExecutionRun.status == "failed")
        .order_by(ExecutionRun.created_at.desc())  # type: ignore[attr-defined]
        .limit(5)
    ).all()

    recent_exceptions = []
    for run in failed_runs:
        # Try to resolve system name via execution_plan -> system
        plan = session.get(ExecutionPlan, run.execution_plan_id)
        system_name = "unknown"
        task_name = "unknown"
        if plan and plan.resolved_system_id:
            sys = session.get(System, plan.resolved_system_id)
            if sys:
                system_name = sys.name
        recent_exceptions.append({
            "id": str(run.id),
            "task_name": task_name,
            "system_name": system_name,
            "status": run.status,
            "created_at": run.created_at.isoformat(),
        })

    return DashboardSummary(
        today_runs=today_runs or 0,
        active_tasks=active_tasks or 0,
        systems_count=systems_count or 0,
        recent_failures_24h=recent_failures_24h or 0,
        recent_exceptions=recent_exceptions,
    )


@router.get("/systems", response_model=list[SystemItem])
def list_systems(
    session: ConsoleDep,
    _: User = Depends(require_console_user),
) -> list[SystemItem]:
    systems = session.exec(select(System)).all()
    result = []
    for sys in systems:
        task_count = session.exec(
            select(func.count(PageCheck.id))
            .join(PageAsset, PageCheck.page_asset_id == PageAsset.id)
            .where(PageAsset.system_id == sys.id)
        ).one()
        result.append(
            SystemItem(
                id=sys.id,
                name=sys.name,
                base_url=sys.base_url,
                status=_system_status(sys),
                task_count=task_count or 0,
            )
        )
    return result


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug or "system"


@router.post("/systems", status_code=201, response_model=SystemCreated)
def onboard_system(
    body: SystemCreateRequest,
    session: ConsoleDep,
    _: User = Depends(require_console_user),
) -> SystemCreated:
    base_code = _slugify(body.name)
    code = base_code
    suffix = 1
    while session.exec(select(System).where(System.code == code)).first():
        code = f"{base_code}_{suffix}"
        suffix += 1

    system = System(
        code=code,
        name=body.name,
        base_url=body.base_url,
        framework_type="unknown",
    )
    session.add(system)
    session.commit()
    session.refresh(system)

    return SystemCreated(
        id=system.id,
        name=system.name,
        base_url=system.base_url,
        status="onboarding",
    )
