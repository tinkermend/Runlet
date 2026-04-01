import sys
from types import ModuleType

import pytest

from app.domains.auth_service.browser_login import PlaywrightBrowserLoginAdapter


class FakeTimeoutError(Exception):
    pass


class FakeBrowserContext:
    def __init__(self, storage_state: dict[str, object]) -> None:
        self._storage_state = storage_state

    async def storage_state(self) -> dict[str, object]:
        return self._storage_state


class FakePage:
    def __init__(
        self,
        *,
        login_url: str,
        storage_state: dict[str, object],
        post_click_url: str,
        wait_for_url_timeout: bool,
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
