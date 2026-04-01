from __future__ import annotations

from typing import Protocol

from app.domains.auth_service.schemas import BrowserLoginResult


class BrowserLoginFailure(RuntimeError):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class BrowserLoginAdapter(Protocol):
    async def login(
        self,
        *,
        login_url: str,
        username: str,
        password: str,
        auth_type: str,
        selectors: dict[str, object] | None,
    ) -> BrowserLoginResult: ...


class PlaywrightBrowserLoginAdapter:
    async def login(
        self,
        *,
        login_url: str,
        username: str,
        password: str,
        auth_type: str,
        selectors: dict[str, object] | None,
    ) -> BrowserLoginResult:
        del auth_type
        selectors = selectors or {}
        required_keys = ("username", "password", "submit")
        missing_keys = [key for key in required_keys if key not in selectors]
        if missing_keys:
            raise BrowserLoginFailure(
                f"missing login selectors: {', '.join(missing_keys)}",
                retryable=False,
            )

        try:
            from playwright.async_api import async_playwright
        except ModuleNotFoundError as exc:  # pragma: no cover - exercised only with Playwright installed
            raise BrowserLoginFailure("playwright is not installed", retryable=False) from exc

        try:
            async with async_playwright() as playwright:  # pragma: no cover - browser integration is faked in tests
                browser = await playwright.chromium.launch(headless=True)
                try:
                    page = await browser.new_page()
                    await page.goto(login_url, wait_until="domcontentloaded")
                    await page.fill(str(selectors["username"]), username)
                    await page.fill(str(selectors["password"]), password)
                    await page.click(str(selectors["submit"]))
                    await page.wait_for_load_state("networkidle")
                    storage_state = await page.context.storage_state()
                finally:
                    await browser.close()
        except BrowserLoginFailure:
            raise
        except Exception as exc:  # pragma: no cover - depends on target site behavior
            raise BrowserLoginFailure(str(exc), retryable=True) from exc

        return BrowserLoginResult(storage_state=storage_state)
