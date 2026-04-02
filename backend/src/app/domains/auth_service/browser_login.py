from __future__ import annotations

from typing import Protocol

from app.config.settings import settings
from app.domains.auth_service.captcha_solver import (
    CaptchaDisabledError,
    CaptchaNotImplementedError,
    CaptchaSolveError,
    CaptchaSolver,
    build_captcha_solver,
)
from app.domains.auth_service.schemas import BrowserLoginResult, CaptchaChallenge


class BrowserLoginFailure(RuntimeError):
    def __init__(self, message: str, *, retryable: bool, code: str | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.code = code or message


def normalize_auth_mode(auth_type: str) -> str:
    normalized = auth_type.strip().lower()
    if normalized in {"", "form", "none", "no_captcha"}:
        return "none"
    if normalized in {"image_captcha", "slider_captcha", "sms_captcha"}:
        return normalized
    raise ValueError("unsupported_auth_mode")


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
    _POST_LOGIN_URL_TIMEOUT_MS = 10_000
    _POST_LOGIN_SETTLE_MS = 500

    def __init__(
        self,
        *,
        captcha_solver: CaptchaSolver | None = None,
        playwright_headless: bool | None = None,
    ) -> None:
        self.captcha_solver = captcha_solver or build_captcha_solver(settings=settings)
        self.playwright_headless = (
            settings.playwright_headless
            if playwright_headless is None
            else playwright_headless
        )

    async def login(
        self,
        *,
        login_url: str,
        username: str,
        password: str,
        auth_type: str,
        selectors: dict[str, object] | None,
    ) -> BrowserLoginResult:
        selectors = selectors or {}
        required_keys = ("username", "password", "submit")
        missing_keys = [key for key in required_keys if key not in selectors]
        if missing_keys:
            raise BrowserLoginFailure(
                f"missing login selectors: {', '.join(missing_keys)}",
                retryable=False,
            )
        auth_mode = normalize_auth_mode(auth_type)

        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
            from playwright.async_api import async_playwright
        except ModuleNotFoundError as exc:  # pragma: no cover - exercised only with Playwright installed
            raise BrowserLoginFailure("playwright is not installed", retryable=False) from exc

        try:
            async with async_playwright() as playwright:  # pragma: no cover - browser integration is faked in tests
                browser = await playwright.chromium.launch(
                    headless=self.playwright_headless
                )
                try:
                    page = await browser.new_page()
                    try:
                        await page.goto(login_url, wait_until="domcontentloaded")
                    except Exception as exc:
                        raise BrowserLoginFailure(
                            "page_open_failed",
                            retryable=True,
                        ) from exc
                    await page.fill(str(selectors["username"]), username)
                    await page.fill(str(selectors["password"]), password)
                    await self._handle_captcha(
                        page=page,
                        auth_mode=auth_mode,
                        selectors=selectors,
                    )
                    await page.click(str(selectors["submit"]))
                    try:
                        await page.wait_for_url(
                            lambda url: url != login_url,
                            timeout=self._POST_LOGIN_URL_TIMEOUT_MS,
                        )
                    except PlaywrightTimeoutError:
                        # Some pages keep background requests alive after login or
                        # update auth state in-place without reaching network idle.
                        pass
                    await page.wait_for_timeout(self._POST_LOGIN_SETTLE_MS)
                    storage_state = await page.context.storage_state()
                finally:
                    await browser.close()
        except BrowserLoginFailure:
            raise
        except Exception as exc:  # pragma: no cover - depends on target site behavior
            raise BrowserLoginFailure(str(exc), retryable=True) from exc

        return BrowserLoginResult(storage_state=storage_state, auth_mode=auth_mode)

    async def _handle_captcha(
        self,
        *,
        page,
        auth_mode: str,
        selectors: dict[str, object],
    ) -> None:
        if auth_mode == "none":
            return
        if auth_mode == "image_captcha":
            await self._solve_image_captcha(page=page, selectors=selectors)
            return
        if auth_mode == "slider_captcha":
            await self._solve_slider_captcha(page=page, selectors=selectors)
            return
        if auth_mode == "sms_captcha":
            raise BrowserLoginFailure("not_implemented", retryable=False)
        raise BrowserLoginFailure("unsupported_auth_mode", retryable=False)

    async def _solve_image_captcha(self, *, page, selectors: dict[str, object]) -> None:
        required_keys = ("captcha_image", "captcha_input")
        self._ensure_captcha_selectors(
            selectors=selectors,
            required_keys=required_keys,
        )
        try:
            image_bytes = await page.locator(str(selectors["captcha_image"])).screenshot()
            solution = self.captcha_solver.solve_image(
                CaptchaChallenge(
                    kind="image_captcha",
                    image_bytes=image_bytes,
                )
            )
        except CaptchaNotImplementedError as exc:
            raise BrowserLoginFailure("not_implemented", retryable=False) from exc
        except (CaptchaDisabledError, CaptchaSolveError) as exc:
            raise BrowserLoginFailure("captcha_solve_failed", retryable=True) from exc

        if not solution.text:
            raise BrowserLoginFailure("captcha_solve_failed", retryable=True)
        await page.fill(str(selectors["captcha_input"]), solution.text)

    async def _solve_slider_captcha(self, *, page, selectors: dict[str, object]) -> None:
        required_keys = ("slider_background", "slider_piece", "slider_handle")
        self._ensure_captcha_selectors(
            selectors=selectors,
            required_keys=required_keys,
        )
        try:
            background_bytes = await page.locator(
                str(selectors["slider_background"])
            ).screenshot()
            piece_bytes = await page.locator(str(selectors["slider_piece"])).screenshot()
            solution = self.captcha_solver.solve_slider(
                CaptchaChallenge(
                    kind="slider_captcha",
                    image_bytes=background_bytes,
                    puzzle_bytes=piece_bytes,
                )
            )
        except CaptchaNotImplementedError as exc:
            raise BrowserLoginFailure("not_implemented", retryable=False) from exc
        except (CaptchaDisabledError, CaptchaSolveError) as exc:
            raise BrowserLoginFailure("captcha_solve_failed", retryable=True) from exc

        if solution.offset_x is None:
            raise BrowserLoginFailure("captcha_solve_failed", retryable=True)

        handle_box = await page.locator(str(selectors["slider_handle"])).bounding_box()
        if handle_box is None:
            raise BrowserLoginFailure("captcha_detect_failed", retryable=True)

        start_x = handle_box["x"] + handle_box["width"] / 2
        start_y = handle_box["y"] + handle_box["height"] / 2
        await page.mouse.move(start_x, start_y)
        await page.mouse.down()
        await page.mouse.move(start_x + solution.offset_x, start_y, steps=10)
        await page.mouse.up()

    def _ensure_captcha_selectors(
        self,
        *,
        selectors: dict[str, object],
        required_keys: tuple[str, ...],
    ) -> None:
        missing_keys = [key for key in required_keys if key not in selectors]
        if missing_keys:
            raise BrowserLoginFailure("captcha_detect_failed", retryable=False)
