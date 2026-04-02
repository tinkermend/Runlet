from __future__ import annotations

import re


class PlaywrightRunnerRuntime:
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
            await page.get_by_role("link", name=label).wait_for(state="visible")
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


def _route_pattern(route_path: str) -> str:
    return f".*{re.escape(route_path)}"
