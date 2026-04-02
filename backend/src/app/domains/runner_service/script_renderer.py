from __future__ import annotations

import hashlib
import re
from uuid import UUID

from pydantic import BaseModel, field_validator
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from app.infrastructure.db.models.assets import ModulePlan, PageAsset, PageCheck
from app.infrastructure.db.models.crawl import Page
from app.infrastructure.db.models.execution import ScriptRender
from app.infrastructure.db.models.systems import System
from app.shared.enums import RenderResultStatus


def _validate_render_mode(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"runtime", "published"}:
        raise ValueError("render_mode must be runtime or published")
    return normalized


class RenderScriptRequest(BaseModel):
    render_mode: str = "runtime"

    @field_validator("render_mode", mode="before")
    @classmethod
    def validate_render_mode(cls, value: str) -> str:
        return _validate_render_mode(value)


class RenderScriptResult(BaseModel):
    page_check_id: UUID
    script_render_id: UUID
    render_mode: str
    script_path: str
    script_text: str


class ScriptRenderer:
    def __init__(self, *, session: Session | AsyncSession) -> None:
        self.session = session

    async def render_page_check(
        self,
        *,
        page_check_id: UUID,
        render_mode: str = "runtime",
    ) -> RenderScriptResult:
        normalized_mode = _validate_render_mode(render_mode)

        page_check = await self._get(PageCheck, page_check_id)
        if page_check is None:
            raise ValueError(f"page check {page_check_id} not found")
        if page_check.module_plan_id is None:
            raise ValueError(f"page check {page_check_id} has no module plan")

        module_plan = await self._get(ModulePlan, page_check.module_plan_id)
        if module_plan is None:
            raise ValueError(f"module plan {page_check.module_plan_id} not found")

        page_asset = await self._get(PageAsset, page_check.page_asset_id)
        if page_asset is None:
            raise ValueError(f"page asset {page_check.page_asset_id} not found")

        page = await self._get(Page, page_asset.page_id)
        if page is None:
            raise ValueError(f"page {page_asset.page_id} not found")

        system = await self._get(System, page_asset.system_id)
        if system is None:
            raise ValueError(f"system {page_asset.system_id} not found")

        script_path = _build_script_path(
            asset_key=page_asset.asset_key,
            check_code=page_check.check_code,
            render_mode=normalized_mode,
        )
        auth_policy = _extract_auth_policy(module_plan.steps_json)
        script_text = _render_script(
            steps_json=module_plan.steps_json,
            base_url=system.base_url,
            render_mode=normalized_mode,
            auth_policy=auth_policy,
        )

        script_render = ScriptRender(
            execution_plan_id=None,
            render_mode=normalized_mode,
            render_result=RenderResultStatus.SUCCESS,
            script_body=script_text,
            render_metadata={
                "page_check_id": str(page_check.id),
                "page_asset_id": str(page_asset.id),
                "asset_key": page_asset.asset_key,
                "asset_version": page_asset.asset_version,
                "system_id": str(system.id),
                "base_url": system.base_url,
                "module_plan_id": str(module_plan.id),
                "plan_version": module_plan.plan_version,
                "runtime_policy": normalized_mode,
                "auth_policy": auth_policy,
                "renderer_version": "v1",
                "script_sha256": hashlib.sha256(script_text.encode("utf-8")).hexdigest(),
                "script_path": script_path,
                "check_code": page_check.check_code,
            },
        )
        self.session.add(script_render)
        await self._commit()
        await self._refresh(script_render)

        return RenderScriptResult(
            page_check_id=page_check.id,
            script_render_id=script_render.id,
            render_mode=normalized_mode,
            script_path=script_path,
            script_text=script_text,
        )

    async def _get(self, model, identifier):
        if isinstance(self.session, AsyncSession):
            return await self.session.get(model, identifier)
        return self.session.get(model, identifier)

    async def _commit(self) -> None:
        if isinstance(self.session, AsyncSession):
            await self.session.commit()
            return
        self.session.commit()

    async def _refresh(self, model) -> None:
        if isinstance(self.session, AsyncSession):
            await self.session.refresh(model)
            return
        self.session.refresh(model)


def _build_script_path(*, asset_key: str, check_code: str, render_mode: str) -> str:
    safe_asset_key = _slugify(asset_key)
    safe_check_code = _slugify(check_code)
    return f"generated/{safe_asset_key}_{safe_check_code}_{render_mode}.py"


def _render_script(
    *,
    steps_json: list[dict[str, object]],
    base_url: str,
    render_mode: str,
    auth_policy: str,
) -> str:
    step_lines: list[str] = []
    helper_needs_re = False

    for raw_step in steps_json:
        module = str(raw_step.get("module") or "")
        params = raw_step.get("params") if isinstance(raw_step.get("params"), dict) else {}

        if module == "auth.inject_state":
            continue
        if module == "nav.menu_chain":
            menu_chain = [str(item) for item in params.get("menu_chain", []) if item is not None]
            route_path = str(params.get("route_path") or "")
            step_lines.append(f"        await navigate_menu_chain(page, {menu_chain!r}, {route_path!r})")
            continue
        if module == "page.wait_ready":
            route_path = str(params.get("route_path") or "")
            helper_needs_re = True
            step_lines.append(
                f"        await page.wait_for_url(re.compile({_route_pattern(route_path)!r}))"
            )
            continue
        if module == "assert.table_visible":
            step_lines.append("        await expect(page.get_by_role(\"table\")).to_be_visible()")
            continue
        if module in {"assert.page_open", "assert.page_ready"}:
            route_path = str(params.get("route_path") or "")
            helper_needs_re = True
            step_lines.append(
                f"        await expect(page).to_have_url(re.compile({_route_pattern(route_path)!r}))"
            )
            continue
        if module == "action.open_create_modal":
            helper_needs_re = True
            step_lines.append(
                "        await page.get_by_role(\"button\", name=re.compile(\"新增|新建|创建\")).click()"
            )
            continue
        step_lines.append(f"        # Unsupported module preserved for review: {module}")

    imports = ["from playwright.async_api import async_playwright, expect"]
    if helper_needs_re:
        imports.insert(0, "import re")

    header = "\n".join(imports)
    context_block = (
        "        context_kwargs = {}\n"
        "        context = await browser.new_context(**context_kwargs)\n"
    )

    body = "\n".join(step_lines) if step_lines else "        pass"
    return (
        f"{header}\n\n\n"
        "async def navigate_menu_chain(page, menu_chain: list[str], route_path: str) -> None:\n"
        "    await page.goto(f\"{BASE_URL}{route_path}\")\n"
        "    for label in menu_chain:\n"
        "        await page.get_by_role(\"link\", name=label).wait_for(state=\"visible\")\n"
        "\n\n"
        "async def apply_auth_policy(context, auth_policy: str) -> None:\n"
        "    if auth_policy != \"server_injected\":\n"
        "        raise ValueError(f\"unsupported auth policy: {auth_policy}\")\n"
        "    # Authentication is injected by the platform runtime, not by this script.\n"
        "\n\n"
        "async def run() -> None:\n"
        "    async with async_playwright() as playwright:\n"
        "        browser = await playwright.chromium.launch(headless=True)\n"
        f"        # Auth policy: {auth_policy} ({render_mode})\n"
        f"{context_block}"
        "        page = await context.new_page()\n"
        "        await apply_auth_policy(context, AUTH_POLICY)\n"
        f"{body}\n"
        "        await context.close()\n"
        "        await browser.close()\n\n\n"
        f"AUTH_POLICY = {auth_policy!r}\n"
        f"BASE_URL = {base_url!r}\n"
    )


def _extract_auth_policy(steps_json: list[dict[str, object]]) -> str:
    for raw_step in steps_json:
        if str(raw_step.get("module") or "") != "auth.inject_state":
            continue
        params = raw_step.get("params")
        if not isinstance(params, dict):
            break
        policy = str(params.get("policy") or "").strip().lower()
        if policy:
            return policy
        break
    return "server_injected"


def _route_pattern(route_path: str) -> str:
    return f".*{re.escape(route_path)}"


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip())
    normalized = normalized.strip("_")
    return normalized or "render"
