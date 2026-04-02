import sys
from types import ModuleType

import pytest

from app.domains.auth_service.browser_login import (
    BrowserLoginFailure,
    PlaywrightBrowserLoginAdapter,
)
from app.domains.auth_service.captcha_solver import CaptchaNotImplementedError
from app.domains.auth_service.schemas import CaptchaChallenge, CaptchaSolution


class FakeTimeoutError(Exception):
    pass


class FakeBrowserContext:
    def __init__(self, storage_state: dict[str, object]) -> None:
        self._storage_state = storage_state

    async def storage_state(self) -> dict[str, object]:
        return self._storage_state


class FakeMouse:
    def __init__(self) -> None:
        self.move_calls: list[tuple[float, float, int | None]] = []
        self.down_calls = 0
        self.up_calls = 0

    async def move(self, x: float, y: float, *, steps: int | None = None) -> None:
        self.move_calls.append((x, y, steps))

    async def down(self) -> None:
        self.down_calls += 1

    async def up(self) -> None:
        self.up_calls += 1


class FakeLocator:
    def __init__(
        self,
        *,
        screenshot_bytes: bytes | None = None,
        bounding_box: dict[str, float] | None = None,
    ) -> None:
        self.screenshot_bytes = screenshot_bytes
        self.bounding_box_value = bounding_box
        self.screenshot_calls = 0
        self.bounding_box_calls = 0

    async def screenshot(self) -> bytes:
        self.screenshot_calls += 1
        if self.screenshot_bytes is None:
            raise AssertionError("unexpected screenshot request")
        return self.screenshot_bytes

    async def bounding_box(self) -> dict[str, float] | None:
        self.bounding_box_calls += 1
        return self.bounding_box_value


class FakePage:
    def __init__(
        self,
        *,
        login_url: str,
        storage_state: dict[str, object],
        post_click_url: str,
        wait_for_url_timeout: bool,
        locators: dict[str, FakeLocator] | None = None,
    ) -> None:
        self.url = login_url
        self.context = FakeBrowserContext(storage_state)
        self.post_click_url = post_click_url
        self.wait_for_url_timeout = wait_for_url_timeout
        self.goto_calls: list[tuple[str, str]] = []
        self.fill_calls: list[tuple[str, str]] = []
        self.click_calls: list[str] = []
        self.wait_for_url_calls: list[int] = []
        self.wait_for_timeout_calls: list[int] = []
        self.locators = locators or {}
        self.locator_calls: list[str] = []
        self.mouse = FakeMouse()

    async def goto(self, url: str, *, wait_until: str) -> None:
        self.goto_calls.append((url, wait_until))
        self.url = url

    async def fill(self, selector: str, value: str) -> None:
        self.fill_calls.append((selector, value))

    async def click(self, selector: str) -> None:
        self.click_calls.append(selector)
        self.url = self.post_click_url

    async def wait_for_url(self, predicate, *, timeout: int) -> None:
        self.wait_for_url_calls.append(timeout)
        if self.wait_for_url_timeout:
            raise FakeTimeoutError("Timeout 10000ms exceeded.")
        assert predicate(self.url) is True

    async def wait_for_timeout(self, timeout: int) -> None:
        self.wait_for_timeout_calls.append(timeout)

    def locator(self, selector: str) -> FakeLocator:
        self.locator_calls.append(selector)
        locator = self.locators.get(selector)
        if locator is None:
            raise AssertionError(f"unexpected locator request: {selector}")
        return locator


class FakeBrowser:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.closed = False

    async def new_page(self) -> FakePage:
        return self.page

    async def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser
        self.headless_calls: list[bool] = []

    async def launch(self, *, headless: bool) -> FakeBrowser:
        self.headless_calls.append(headless)
        return self.browser


class FakePlaywright:
    def __init__(self, chromium: FakeChromium) -> None:
        self.chromium = chromium


class FakePlaywrightContextManager:
    def __init__(self, playwright: FakePlaywright) -> None:
        self.playwright = playwright

    async def __aenter__(self) -> FakePlaywright:
        return self.playwright

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


def install_fake_async_api(
    monkeypatch: pytest.MonkeyPatch,
    *,
    page: FakePage,
) -> tuple[FakePage, FakeBrowser, FakeChromium]:
    browser = FakeBrowser(page)
    chromium = FakeChromium(browser)
    playwright = FakePlaywright(chromium)
    module = ModuleType("playwright.async_api")
    module.TimeoutError = FakeTimeoutError
    module.async_playwright = lambda: FakePlaywrightContextManager(playwright)
    monkeypatch.setitem(sys.modules, "playwright.async_api", module)
    return page, browser, chromium


class FakeCaptchaSolver:
    def __init__(
        self,
        *,
        image_text: str = "ABCD",
        slider_offset_x: int = 42,
    ) -> None:
        self.image_text = image_text
        self.slider_offset_x = slider_offset_x
        self.image_challenges: list[CaptchaChallenge] = []
        self.slider_challenges: list[CaptchaChallenge] = []
        self.sms_challenges: list[CaptchaChallenge] = []

    def solve_image(self, challenge: CaptchaChallenge) -> CaptchaSolution:
        self.image_challenges.append(challenge)
        return CaptchaSolution(kind=challenge.kind, text=self.image_text)

    def solve_slider(self, challenge: CaptchaChallenge) -> CaptchaSolution:
        self.slider_challenges.append(challenge)
        return CaptchaSolution(kind=challenge.kind, offset_x=self.slider_offset_x)

    def solve_sms(self, challenge: CaptchaChallenge) -> CaptchaSolution:
        self.sms_challenges.append(challenge)
        raise CaptchaNotImplementedError("sms captcha solver is reserved but not implemented")


@pytest.mark.anyio
async def test_login_waits_for_url_change_before_capturing_storage_state(monkeypatch):
    login_url = "https://erp.example.com/login"
    page, browser, chromium = install_fake_async_api(
        monkeypatch,
        page=FakePage(
            login_url=login_url,
            storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
            post_click_url="https://erp.example.com/home",
            wait_for_url_timeout=False,
        ),
    )

    result = await PlaywrightBrowserLoginAdapter().login(
        login_url=login_url,
        username="erp-user",
        password="erp-password",
        auth_type="form",
        selectors={
            "username": "#username",
            "password": "#password",
            "submit": "button[type=submit]",
        },
    )

    assert result.storage_state["cookies"][0]["name"] == "sid"
    assert page.goto_calls == [(login_url, "domcontentloaded")]
    assert page.fill_calls == [
        ("#username", "erp-user"),
        ("#password", "erp-password"),
    ]
    assert page.click_calls == ["button[type=submit]"]
    assert page.wait_for_url_calls == [10_000]
    assert page.wait_for_timeout_calls == [500]
    assert chromium.headless_calls == [True]
    assert browser.closed is True


@pytest.mark.anyio
async def test_login_falls_back_to_short_settle_when_url_never_changes(monkeypatch):
    login_url = "https://erp.example.com/login"
    page, browser, _ = install_fake_async_api(
        monkeypatch,
        page=FakePage(
            login_url=login_url,
            storage_state={
                "origins": [
                    {
                        "origin": "https://erp.example.com",
                        "localStorage": [{"name": "token", "value": "xyz"}],
                    }
                ]
            },
            post_click_url=login_url,
            wait_for_url_timeout=True,
        ),
    )

    result = await PlaywrightBrowserLoginAdapter().login(
        login_url=login_url,
        username="erp-user",
        password="erp-password",
        auth_type="form",
        selectors={
            "username": "#username",
            "password": "#password",
            "submit": "button[type=submit]",
        },
    )

    assert result.storage_state["origins"][0]["origin"] == "https://erp.example.com"
    assert page.wait_for_url_calls == [10_000]
    assert page.wait_for_timeout_calls == [500]
    assert browser.closed is True


@pytest.mark.anyio
async def test_login_solves_image_captcha_before_submit(monkeypatch):
    login_url = "https://erp.example.com/login"
    solver = FakeCaptchaSolver(image_text="7KLM")
    page, browser, _ = install_fake_async_api(
        monkeypatch,
        page=FakePage(
            login_url=login_url,
            storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
            post_click_url="https://erp.example.com/home",
            wait_for_url_timeout=False,
            locators={
                ".captcha-image": FakeLocator(screenshot_bytes=b"captcha-image"),
            },
        ),
    )

    result = await PlaywrightBrowserLoginAdapter(captcha_solver=solver).login(
        login_url=login_url,
        username="erp-user",
        password="erp-password",
        auth_type="image_captcha",
        selectors={
            "username": "#username",
            "password": "#password",
            "captcha_input": "#captcha",
            "captcha_image": ".captcha-image",
            "submit": "button[type=submit]",
        },
    )

    assert result.storage_state["cookies"][0]["name"] == "sid"
    assert page.fill_calls == [
        ("#username", "erp-user"),
        ("#password", "erp-password"),
        ("#captcha", "7KLM"),
    ]
    assert solver.image_challenges[0].image_bytes == b"captcha-image"
    assert browser.closed is True


@pytest.mark.anyio
async def test_login_solves_slider_before_submit(monkeypatch):
    login_url = "https://erp.example.com/login"
    solver = FakeCaptchaSolver(slider_offset_x=42)
    page, browser, _ = install_fake_async_api(
        monkeypatch,
        page=FakePage(
            login_url=login_url,
            storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
            post_click_url="https://erp.example.com/home",
            wait_for_url_timeout=False,
            locators={
                ".slider-bg": FakeLocator(screenshot_bytes=b"background-image"),
                ".slider-piece": FakeLocator(screenshot_bytes=b"slider-piece"),
                ".slider-handle": FakeLocator(
                    bounding_box={"x": 100.0, "y": 40.0, "width": 40.0, "height": 20.0}
                ),
            },
        ),
    )

    result = await PlaywrightBrowserLoginAdapter(captcha_solver=solver).login(
        login_url=login_url,
        username="erp-user",
        password="erp-password",
        auth_type="slider_captcha",
        selectors={
            "username": "#username",
            "password": "#password",
            "submit": "button[type=submit]",
            "slider_background": ".slider-bg",
            "slider_piece": ".slider-piece",
            "slider_handle": ".slider-handle",
        },
    )

    assert result.storage_state["cookies"][0]["name"] == "sid"
    assert solver.slider_challenges[0].image_bytes == b"background-image"
    assert solver.slider_challenges[0].puzzle_bytes == b"slider-piece"
    assert page.mouse.move_calls == [
        (120.0, 50.0, None),
        (162.0, 50.0, 10),
    ]
    assert page.mouse.down_calls == 1
    assert page.mouse.up_calls == 1
    assert browser.closed is True


@pytest.mark.anyio
async def test_login_respects_playwright_headless_setting(monkeypatch):
    login_url = "https://erp.example.com/login"
    page, browser, chromium = install_fake_async_api(
        monkeypatch,
        page=FakePage(
            login_url=login_url,
            storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
            post_click_url="https://erp.example.com/home",
            wait_for_url_timeout=False,
        ),
    )

    result = await PlaywrightBrowserLoginAdapter(playwright_headless=False).login(
        login_url=login_url,
        username="erp-user",
        password="erp-password",
        auth_type="none",
        selectors={
            "username": "#username",
            "password": "#password",
            "submit": "button[type=submit]",
        },
    )

    assert result.storage_state["cookies"][0]["name"] == "sid"
    assert chromium.headless_calls == [False]
    assert browser.closed is True


@pytest.mark.anyio
async def test_login_rejects_sms_captcha_as_not_implemented(monkeypatch):
    login_url = "https://erp.example.com/login"
    install_fake_async_api(
        monkeypatch,
        page=FakePage(
            login_url=login_url,
            storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
            post_click_url="https://erp.example.com/home",
            wait_for_url_timeout=False,
        ),
    )

    with pytest.raises(BrowserLoginFailure) as exc_info:
        await PlaywrightBrowserLoginAdapter(captcha_solver=FakeCaptchaSolver()).login(
            login_url=login_url,
            username="erp-user",
            password="erp-password",
            auth_type="sms_captcha",
            selectors={
                "username": "#username",
                "password": "#password",
                "submit": "button[type=submit]",
            },
        )

    assert str(exc_info.value) == "not_implemented"
