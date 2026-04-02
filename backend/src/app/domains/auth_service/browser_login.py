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
    _LOGIN_PAGE_MAX_ATTEMPTS = 3
    _LOGIN_PAGE_READY_TIMEOUT_MS = 5_000
    _LOGIN_PAGE_READY_POLL_MS = 250
    _LOGIN_PAGE_RETRY_WAIT_MS = 1_000
    _SLIDER_POST_DRAG_WAIT_MS = 1_000
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
                    await self._open_login_page(
                        page=page,
                        login_url=login_url,
                        selectors=selectors,
                    )
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
                    await self._ensure_login_completed(
                        page=page,
                        login_url=login_url,
                        selectors=selectors,
                    )
                    storage_state = await page.context.storage_state()
                finally:
                    await browser.close()
        except BrowserLoginFailure:
            raise
        except Exception as exc:  # pragma: no cover - depends on target site behavior
            raise BrowserLoginFailure(str(exc), retryable=True) from exc

        return BrowserLoginResult(storage_state=storage_state, auth_mode=auth_mode)

    async def _open_login_page(
        self,
        *,
        page,
        login_url: str,
        selectors: dict[str, object],
    ) -> None:
        max_attempts = self._coerce_positive_int(
            selectors.get("login_page_max_attempts"),
            default=self._LOGIN_PAGE_MAX_ATTEMPTS,
        )
        ready_timeout_ms = self._coerce_positive_int(
            selectors.get("login_page_ready_timeout_ms"),
            default=self._LOGIN_PAGE_READY_TIMEOUT_MS,
        )
        ready_poll_ms = self._coerce_positive_int(
            selectors.get("login_page_ready_poll_ms"),
            default=self._LOGIN_PAGE_READY_POLL_MS,
        )
        retry_wait_ms = self._coerce_positive_int(
            selectors.get("login_page_retry_wait_ms"),
            default=self._LOGIN_PAGE_RETRY_WAIT_MS,
        )
        last_failure: BrowserLoginFailure | None = None

        for attempt in range(max_attempts):
            try:
                await page.goto(login_url, wait_until="domcontentloaded")
            except Exception as exc:
                last_failure = BrowserLoginFailure(
                    "page_open_failed",
                    retryable=True,
                )
                if attempt == max_attempts - 1:
                    raise last_failure from exc
            else:
                if await self._wait_for_login_form_ready(
                    page=page,
                    selectors=selectors,
                    timeout_ms=ready_timeout_ms,
                    poll_ms=ready_poll_ms,
                ):
                    return
                last_failure = BrowserLoginFailure("login_page_not_ready", retryable=True)
                if attempt == max_attempts - 1:
                    raise last_failure

            await page.wait_for_timeout(retry_wait_ms)

        raise last_failure or BrowserLoginFailure("login_page_not_ready", retryable=True)

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
        if self._resolve_slider_mode(selectors) == "drag":
            self._ensure_captcha_selectors(
                selectors=selectors,
                required_keys=("slider_background", "slider_handle"),
            )
            await self._drag_slider_to_track_end(page=page, selectors=selectors)
            return

        self._ensure_captcha_selectors(
            selectors=selectors,
            required_keys=("slider_background", "slider_piece", "slider_handle"),
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

    def _resolve_slider_mode(self, selectors: dict[str, object]) -> str:
        raw_mode = selectors.get("slider_mode")
        if isinstance(raw_mode, str):
            normalized = raw_mode.strip().lower()
            if normalized in {"drag", "drag_slider"}:
                return "drag"
            if normalized in {"puzzle", "ocr", "puzzle_slider"}:
                return "puzzle"

        slider_piece = selectors.get("slider_piece")
        slider_handle = selectors.get("slider_handle")
        if (
            isinstance(slider_piece, str)
            and isinstance(slider_handle, str)
            and slider_piece
            and slider_piece == slider_handle
        ):
            return "drag"
        return "puzzle"

    async def _drag_slider_to_track_end(self, *, page, selectors: dict[str, object]) -> None:
        track_box = await page.locator(str(selectors["slider_background"])).bounding_box()
        handle_box = await page.locator(str(selectors["slider_handle"])).bounding_box()
        if track_box is None or handle_box is None:
            raise BrowserLoginFailure("captcha_detect_failed", retryable=True)

        start_x = handle_box["x"] + handle_box["width"] / 2
        start_y = handle_box["y"] + handle_box["height"] / 2
        drag_steps = self._coerce_positive_int(selectors.get("slider_drag_steps"), default=20)
        right_padding = self._coerce_float(
            selectors.get("slider_drag_padding_right"),
            default=2.0,
        )
        target_x = max(
            start_x,
            track_box["x"] + track_box["width"] - handle_box["width"] / 2 - right_padding,
        )

        await page.mouse.move(start_x, start_y)
        await page.mouse.down()
        await page.mouse.move(target_x, start_y, steps=drag_steps)
        await page.mouse.up()
        await page.wait_for_timeout(
            self._coerce_positive_int(
                selectors.get("slider_post_drag_wait_ms"),
                default=self._SLIDER_POST_DRAG_WAIT_MS,
            )
        )

    async def _ensure_login_completed(
        self,
        *,
        page,
        login_url: str,
        selectors: dict[str, object],
    ) -> None:
        if await self._login_form_still_visible(page=page, selectors=selectors):
            raise BrowserLoginFailure("login_not_completed", retryable=True)

    async def _wait_for_login_form_ready(
        self,
        *,
        page,
        selectors: dict[str, object],
        timeout_ms: int,
        poll_ms: int,
    ) -> bool:
        poll_ms = max(poll_ms, 1)
        attempts = max(1, (timeout_ms + poll_ms - 1) // poll_ms)
        for index in range(attempts):
            if await self._login_form_is_ready(page=page, selectors=selectors):
                return True
            if index < attempts - 1:
                await page.wait_for_timeout(poll_ms)
        return False

    async def _login_form_is_ready(self, *, page, selectors: dict[str, object]) -> bool:
        for key in ("username", "password"):
            selector = selectors.get(key)
            if not isinstance(selector, str) or not selector:
                continue
            if not await self._locator_is_visible(page=page, selector=selector):
                return False
        return True

    async def _login_form_still_visible(self, *, page, selectors: dict[str, object]) -> bool:
        for key in ("username", "password"):
            selector = selectors.get(key)
            if not isinstance(selector, str) or not selector:
                continue
            if await self._locator_is_visible(page=page, selector=selector):
                return True
        return False

    async def _locator_is_visible(self, *, page, selector: str) -> bool:
        try:
            locator = page.locator(selector)
            return bool(await locator.is_visible())
        except Exception:
            return False

    def _coerce_positive_int(self, value: object, *, default: int) -> int:
        if isinstance(value, bool):
            return default
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str):
            try:
                parsed = int(value)
            except ValueError:
                return default
            if parsed > 0:
                return parsed
        return default

    def _coerce_float(self, value: object, *, default: float) -> float:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return default
        return default

    def _ensure_captcha_selectors(
        self,
        *,
        selectors: dict[str, object],
        required_keys: tuple[str, ...],
    ) -> None:
        missing_keys = [key for key in required_keys if key not in selectors]
        if missing_keys:
            raise BrowserLoginFailure("captcha_detect_failed", retryable=False)
