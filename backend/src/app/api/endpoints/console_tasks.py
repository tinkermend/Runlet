from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, func, select

from app.domains.control_plane.console_schemas import (
    RunResultItem,
    SystemItem,
    TaskCreateRequest,
    TaskCreated,
    TaskDetail,
    TaskItem,
    TriggerResponse,
    WizardOptions,
)
from app.infrastructure.db.console_session import get_console_db
from app.infrastructure.db.models.assets import PageAsset, PageCheck
from app.infrastructure.db.models.crawl import Page
from app.infrastructure.db.models.execution import (
    ExecutionPlan,
    ExecutionRequest,
    ExecutionRun,
)
from app.infrastructure.db.models.systems import System

router = APIRouter(prefix="/tasks", tags=["console-tasks"])

ConsoleDep = Annotated[Session, Depends(get_console_db)]

AVAILABLE_CHECK_TYPES = [
    "menu_completeness",
    "element_existence",
    "table_render",
    "form_submit",
    "page_load",
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_") or "task"


def _system_item(sys: System, task_count: int) -> SystemItem:
    return SystemItem(
        id=sys.id,
        name=sys.name,
        base_url=sys.base_url,
        status="ready",
        task_count=task_count,
    )


def _resolve_system_name(session: Session, page_check: PageCheck) -> str:
    asset = session.get(PageAsset, page_check.page_asset_id)
    if asset:
        sys = session.get(System, asset.system_id)
        if sys:
            return sys.name
    return "unknown"


def _last_run_for_check(session: Session, check_id: UUID) -> ExecutionRun | None:
    plan = session.exec(
        select(ExecutionPlan)
        .where(ExecutionPlan.resolved_page_check_id == check_id)
        .order_by(ExecutionPlan.id.desc())  # type: ignore[attr-defined]
        .limit(1)
    ).first()
    if not plan:
        return None
    run = session.exec(
        select(ExecutionRun)
        .where(ExecutionRun.execution_plan_id == plan.id)
        .order_by(ExecutionRun.created_at.desc())  # type: ignore[attr-defined]
        .limit(1)
    ).first()
    return run


# IMPORTANT: wizard-options must be defined BEFORE {task_id} routes
@router.get("/wizard-options", response_model=WizardOptions)
def get_wizard_options(session: ConsoleDep) -> WizardOptions:
    systems = session.exec(select(System)).all()
    system_items = []
    for sys in systems:
        task_count = session.exec(
            select(func.count(PageCheck.id))
            .join(PageAsset, PageCheck.page_asset_id == PageAsset.id)
            .where(PageAsset.system_id == sys.id)
        ).one()
        system_items.append(_system_item(sys, task_count or 0))

    return WizardOptions(
        systems=system_items,
        check_types=AVAILABLE_CHECK_TYPES,
    )


@router.get("/", response_model=list[TaskItem])
def list_tasks(session: ConsoleDep) -> list[TaskItem]:
    checks = session.exec(select(PageCheck)).all()
    result = []
    for check in checks:
        system_name = _resolve_system_name(session, check)
        last_run = _last_run_for_check(session, check.id)
        check_types = []
        if check.input_schema and "check_types" in check.input_schema:
            check_types = check.input_schema["check_types"]
        schedule_preset = "manual"
        if check.input_schema and "schedule_preset" in check.input_schema:
            schedule_preset = check.input_schema["schedule_preset"]

        result.append(
            TaskItem(
                id=str(check.id),
                name=check.goal,
                system_name=system_name,
                status=check.lifecycle_status.value if hasattr(check.lifecycle_status, "value") else str(check.lifecycle_status),
                last_run_at=last_run.created_at if last_run else None,
                last_run_status=last_run.status if last_run else None,
                schedule_preset=schedule_preset,
            )
        )
    return result


@router.post("/", status_code=201, response_model=TaskCreated)
def create_task(body: TaskCreateRequest, session: ConsoleDep) -> TaskCreated:
    system = session.get(System, body.system_id)
    if not system:
        raise HTTPException(status_code=404, detail="System not found")

    # Create a minimal Page record as anchor
    page = Page(
        system_id=system.id,
        route_path=f"/{_slugify(body.name)}",
        page_title=body.name,
    )
    session.add(page)
    session.flush()

    # Create a PageAsset linked to the page
    asset_key = f"{system.code}.{_slugify(body.name)}"
    page_asset = PageAsset(
        system_id=system.id,
        page_id=page.id,
        asset_key=asset_key,
        asset_version=_utcnow().strftime("%Y.%m.%d"),
    )
    session.add(page_asset)
    session.flush()

    # Create a PageCheck — store check_types and schedule_preset in input_schema
    check_code = _slugify(body.name)
    page_check = PageCheck(
        page_asset_id=page_asset.id,
        check_code=check_code,
        goal=body.name,
        input_schema={
            "check_types": body.check_types,
            "schedule_preset": body.schedule_preset,
            "timeout_seconds": body.timeout_seconds,
        },
    )
    session.add(page_check)
    session.commit()
    session.refresh(page_check)

    return TaskCreated(id=str(page_check.id), name=page_check.goal)


@router.get("/{task_id}", response_model=TaskDetail)
def get_task(task_id: str, session: ConsoleDep) -> TaskDetail:
    try:
        uid = UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Task not found")

    check = session.get(PageCheck, uid)
    if not check:
        raise HTTPException(status_code=404, detail="Task not found")

    system_name = _resolve_system_name(session, check)

    check_types: list[str] = []
    schedule_preset = "manual"
    if check.input_schema:
        check_types = check.input_schema.get("check_types", [])  # type: ignore[assignment]
        schedule_preset = check.input_schema.get("schedule_preset", "manual")  # type: ignore[assignment]

    # Fetch last 10 runs via execution plans linked to this check
    plans = session.exec(
        select(ExecutionPlan)
        .where(ExecutionPlan.resolved_page_check_id == check.id)
    ).all()
    plan_ids = [p.id for p in plans]

    recent_runs: list[RunResultItem] = []
    if plan_ids:
        runs = session.exec(
            select(ExecutionRun)
            .where(ExecutionRun.execution_plan_id.in_(plan_ids))  # type: ignore[attr-defined]
            .order_by(ExecutionRun.created_at.desc())  # type: ignore[attr-defined]
            .limit(10)
        ).all()
        for run in runs:
            plan = session.get(ExecutionPlan, run.execution_plan_id)
            run_system_name = system_name
            if plan and plan.resolved_system_id:
                sys = session.get(System, plan.resolved_system_id)
                if sys:
                    run_system_name = sys.name
            recent_runs.append(
                RunResultItem(
                    id=run.id,
                    task_name=check.goal,
                    system_name=run_system_name,
                    status=run.status,
                    duration_ms=run.duration_ms,
                    created_at=run.created_at,
                )
            )

    status_val = check.lifecycle_status.value if hasattr(check.lifecycle_status, "value") else str(check.lifecycle_status)

    return TaskDetail(
        id=str(check.id),
        name=check.goal,
        system_name=system_name,
        status=status_val,
        schedule_preset=schedule_preset,
        check_types=check_types,
        recent_runs=recent_runs,
    )


@router.post("/{task_id}/trigger", status_code=202, response_model=TriggerResponse)
def trigger_task(task_id: str, session: ConsoleDep) -> TriggerResponse:
    try:
        uid = UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Task not found")

    check = session.get(PageCheck, uid)
    if not check:
        raise HTTPException(status_code=404, detail="Task not found")

    asset = session.get(PageAsset, check.page_asset_id)
    system_id = asset.system_id if asset else None
    system = session.get(System, system_id) if system_id else None
    system_hint = system.name if system else "unknown"

    # Create a minimal execution chain: request -> plan -> run
    exec_request = ExecutionRequest(
        request_source="console_trigger",
        system_hint=system_hint,
        page_hint=check.goal,
        check_goal=check.goal,
        strictness="balanced",
        time_budget_ms=30_000,
    )
    session.add(exec_request)
    session.flush()

    exec_plan = ExecutionPlan(
        execution_request_id=exec_request.id,
        resolved_system_id=system_id,
        resolved_page_check_id=check.id,
        resolved_page_asset_id=check.page_asset_id,
        execution_track="module_plan",
        auth_policy="server_injected",
    )
    session.add(exec_plan)
    session.flush()

    exec_run = ExecutionRun(
        execution_plan_id=exec_plan.id,
        status="queued",
    )
    session.add(exec_run)
    session.commit()
    session.refresh(exec_run)

    return TriggerResponse(ok=True, run_id=str(exec_run.id))
