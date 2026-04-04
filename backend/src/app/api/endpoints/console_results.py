from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, func, select

from app.api.deps_auth import require_console_user
from app.domains.control_plane.console_schemas import PaginatedResults, RunResultItem
from app.infrastructure.db.console_session import get_console_db
from app.infrastructure.db.models.assets import PageAsset, PageCheck
from app.infrastructure.db.models.execution import ExecutionPlan, ExecutionRun
from app.infrastructure.db.models.identity import User
from app.infrastructure.db.models.systems import System

router = APIRouter(prefix="/results", tags=["console-results"])

ConsoleDep = Annotated[Session, Depends(get_console_db)]


@router.get("/", response_model=PaginatedResults)
def list_results(
    session: ConsoleDep,
    _: User = Depends(require_console_user),
    system_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PaginatedResults:
    base_query = select(ExecutionRun)
    count_query = select(func.count(ExecutionRun.id))

    if status:
        base_query = base_query.where(ExecutionRun.status == status)
        count_query = count_query.where(ExecutionRun.status == status)

    if system_id:
        base_query = (
            base_query
            .join(ExecutionPlan, ExecutionRun.execution_plan_id == ExecutionPlan.id)
            .where(ExecutionPlan.resolved_system_id == system_id)
        )
        count_query = (
            count_query
            .join(ExecutionPlan, ExecutionRun.execution_plan_id == ExecutionPlan.id)
            .where(ExecutionPlan.resolved_system_id == system_id)
        )

    total = session.exec(count_query).one() or 0
    offset = (page - 1) * page_size
    runs = session.exec(
        base_query
        .order_by(ExecutionRun.created_at.desc())  # type: ignore[attr-defined]
        .offset(offset)
        .limit(page_size)
    ).all()

    items = []
    for run in runs:
        plan = session.get(ExecutionPlan, run.execution_plan_id)
        system_name = "unknown"
        task_name = "unknown"
        if plan:
            if plan.resolved_system_id:
                sys = session.get(System, plan.resolved_system_id)
                if sys:
                    system_name = sys.name
            if plan.resolved_page_check_id:
                check = session.get(PageCheck, plan.resolved_page_check_id)
                if check:
                    task_name = check.goal

        items.append(
            RunResultItem(
                id=run.id,
                task_name=task_name,
                system_name=system_name,
                status=run.status,
                duration_ms=run.duration_ms,
                created_at=run.created_at,
            )
        )

    return PaginatedResults(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )
