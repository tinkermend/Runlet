from __future__ import annotations

import re


class PlaywrightRunnerRuntime:
    _MENU_SCOPE_SELECTORS = (
        "#menu_top_mix",
        "nav",
        "aside",
        "[role='menu']",
        "[role='navigation']",
    )

    def __init__(self) -> None:
        self._base_url: str | None = None
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def set_base_url(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def inject_auth_state(self, *, storage_state: dict[str, object]) -> bool:
        await self.close()
        try:
            from playwright.async_api import async_playwright
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise RuntimeError("playwright is not installed") from exc

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._context = await self._browser.new_context(storage_state=storage_state)
        self._page = await self._context.new_page()
        return True

    async def navigate_menu_chain(self, *, menu_chain: list[str], route_path: str) -> bool:
        page = self._require_page()
        await page.goto(self._resolve_url(route_path), wait_until="domcontentloaded")
        for label in menu_chain:
            await self._wait_for_menu_label(page=page, label=label)
        return True

    async def wait_page_ready(self, *, route_path: str) -> bool:
        page = self._require_page()
        await page.wait_for_load_state("domcontentloaded")
        if route_path:
            await page.wait_for_url(re.compile(_route_pattern(route_path)))
        return True

    async def assert_table_visible(self, *, route_path: str | None = None) -> bool:
        del route_path
        from playwright.async_api import expect

        page = self._require_page()
        await expect(page.get_by_role("table")).to_be_visible()
        return True

    async def assert_page_open(self, *, route_path: str) -> bool:
        from playwright.async_api import expect

        page = self._require_page()
        await expect(page).to_have_url(re.compile(_route_pattern(route_path)))
        return True

    async def capture_screenshot(self) -> bytes:
        page = self._require_page()
        return await page.screenshot(full_page=True, type="png")

    async def get_final_url(self) -> str | None:
        page = self._require_page()
        url = str(getattr(page, "url", "") or "").strip()
        return url or None

    async def get_page_title(self) -> str | None:
        page = self._require_page()
        title = str(await page.title() or "").strip()
        return title or None

    async def open_create_modal(self) -> bool:
        page = self._require_page()
        dialogs = page.get_by_role("dialog")
        dialog_count_before = await dialogs.count()
        dialog_visible_before = False
        if dialog_count_before > 0:
            dialog_visible_before = await dialogs.first.is_visible()

        trigger = page.get_by_role("button", name=re.compile("新增|新建|创建")).first
        if await trigger.count() == 0:
            trigger = page.get_by_role("link", name=re.compile("新增|新建|创建")).first
        await trigger.wait_for(state="visible")
        await trigger.click()
        modal = dialogs.first
        await modal.wait_for(state="visible")

        dialog_count_after = await dialogs.count()
        dialog_visible_after = await modal.is_visible()
        dialog_state_changed = dialog_count_after > dialog_count_before or (
            not dialog_visible_before and dialog_visible_after
        )
        if not dialog_state_changed:
            raise RuntimeError("open_create_modal did not change dialog state")
        return True

    async def enter_state(self, *, state_signature: str) -> bool:
        normalized = str(state_signature or "").strip().lower()
        if not normalized:
            return True
        if "modal=" not in normalized:
            return True
        page = self._require_page()
        dialogs = page.get_by_role("dialog")
        if await dialogs.count() > 0 and await dialogs.first.is_visible():
            return True
        try:
            return await self.open_create_modal()
        except Exception:
            return False

    async def resolve_locator_bundle(
        self,
        *,
        locator_bundle: dict[str, object],
        context_constraints: dict[str, object] | None = None,
    ) -> dict[str, object]:
        page = self._require_page()
        candidates = locator_bundle.get("candidates") if isinstance(locator_bundle, dict) else None
        if not isinstance(candidates, list) or not candidates:
            return _build_locator_failure(failure_category="locator_all_failed")

        context_mismatch = False
        ambiguous_match = False
        any_context_matched = False
        base_constraints = context_constraints if isinstance(context_constraints, dict) else {}

        for index, candidate in enumerate(candidates, start=1):
            if not isinstance(candidate, dict):
                continue
            selector = str(candidate.get("selector") or "").strip()
            if not selector:
                continue
            strategy_type = str(candidate.get("strategy_type") or "").strip() or None
            rank = _coerce_positive_int(candidate.get("fallback_rank")) or index
            merged_constraints = dict(base_constraints)
            candidate_constraints = candidate.get("context_constraints")
            if isinstance(candidate_constraints, dict):
                merged_constraints.update(candidate_constraints)
            if not await self._matches_context_constraints(page=page, constraints=merged_constraints):
                context_mismatch = True
                continue
            any_context_matched = True

            resolved = page.locator(selector)
            count = await resolved.count()
            if count == 1:
                target = resolved.first
                await target.wait_for(state="visible")
                return {
                    "matched": True,
                    "matched_rank": rank,
                    "strategy_type": strategy_type,
                    "failure_category": None,
                    "context_mismatch": context_mismatch,
                    "ambiguous_match": ambiguous_match,
                }
            if count > 1:
                ambiguous_match = True
                continue

        if not any_context_matched and context_mismatch:
            return _build_locator_failure(
                failure_category="context_mismatch",
                context_mismatch=True,
                ambiguous_match=ambiguous_match,
            )
        if ambiguous_match:
            return _build_locator_failure(
                failure_category="ambiguous_match",
                context_mismatch=context_mismatch,
                ambiguous_match=True,
            )
        return _build_locator_failure(
            failure_category="locator_all_failed",
            context_mismatch=context_mismatch,
            ambiguous_match=False,
        )

    async def probe_page(self) -> dict[str, object]:
        page = self._require_page()
        return {
            "url": await self.get_final_url(),
            "title": await self.get_page_title(),
            "dialog_count": await page.get_by_role("dialog").count(),
            "table_count": await page.get_by_role("table").count(),
        }

    async def close(self) -> None:
        if self._page is not None:
            await self._page.close()
            self._page = None
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    def _require_page(self):
        if self._page is None:
            raise RuntimeError("playwright runner runtime is not initialized")
        return self._page

    def _resolve_url(self, route_path: str) -> str:
        if not route_path:
            raise RuntimeError("route_path is required")
        if route_path.startswith("http://") or route_path.startswith("https://"):
            return route_path
        if self._base_url is None:
            raise RuntimeError("playwright runner runtime base_url is not configured")
        return f"{self._base_url}{route_path}"

    async def _wait_for_menu_label(self, *, page, label: str) -> None:
        for selector in self._MENU_SCOPE_SELECTORS:
            container = page.locator(selector)
            if await container.count() == 0:
                continue
            scoped_link = container.get_by_role("link", name=label, exact=True).first
            if await scoped_link.count() > 0:
                await scoped_link.wait_for(state="visible")
                return
            scoped_menuitem = container.get_by_role("menuitem", name=label, exact=True).first
            if await scoped_menuitem.count() > 0:
                await scoped_menuitem.wait_for(state="visible")
                return

        global_link = page.get_by_role("link", name=label, exact=True).first
        if await global_link.count() > 0:
            await global_link.wait_for(state="visible")
            return

        global_menuitem = page.get_by_role("menuitem", name=label, exact=True).first
        await global_menuitem.wait_for(state="visible")

    async def _matches_context_constraints(self, *, page, constraints: dict[str, object]) -> bool:
        if not constraints:
            return True

        dialog_count = await page.get_by_role("dialog").count()
        entry_type = str(constraints.get("entry_type") or "").strip().lower()
        if entry_type in {"open_modal", "modal_open"} and dialog_count == 0:
            return False

        modal_title = str(constraints.get("modal_title") or "").strip()
        if modal_title:
            if await page.get_by_role("dialog", name=modal_title, exact=True).count() == 0:
                return False

        requires_dialog = constraints.get("requires_dialog")
        if isinstance(requires_dialog, bool):
            if requires_dialog and dialog_count == 0:
                return False
            if not requires_dialog and dialog_count > 0:
                return False

        return True


def _route_pattern(route_path: str) -> str:
    return f".*{re.escape(route_path)}"


def _coerce_positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


def _build_locator_failure(
    *,
    failure_category: str,
    context_mismatch: bool = False,
    ambiguous_match: bool = False,
) -> dict[str, object]:
    return {
        "matched": False,
        "matched_rank": None,
        "strategy_type": None,
        "failure_category": failure_category,
        "context_mismatch": context_mismatch,
        "ambiguous_match": ambiguous_match,
    }
