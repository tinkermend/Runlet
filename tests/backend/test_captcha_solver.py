import pytest

from app.config.settings import Settings
from app.domains.auth_service.captcha_solver import (
    CaptchaDisabledError,
    CaptchaNotImplementedError,
    DdddOcrCaptchaSolver,
    build_captcha_solver,
)
from app.domains.auth_service.schemas import CaptchaChallenge


class FakeDdddOcrClient:
    def __init__(self) -> None:
        self.classification_calls: list[bytes] = []
        self.slide_match_calls: list[tuple[bytes, bytes]] = []

    def classification(self, image_bytes: bytes) -> str:
        self.classification_calls.append(image_bytes)
        return "ABCD"

    def slide_match(self, target_bytes: bytes, background_bytes: bytes) -> dict[str, list[int]]:
        self.slide_match_calls.append((target_bytes, background_bytes))
        return {"target": [42, 7, 52, 17]}


def test_ddddocr_solver_returns_image_solution() -> None:
    fake_client = FakeDdddOcrClient()
    solver = DdddOcrCaptchaSolver(ocr_client=fake_client)

    solution = solver.solve_image(
        CaptchaChallenge(kind="image_captcha", image_bytes=b"fake-image")
    )

    assert solution.text == "ABCD"
    assert solution.offset_x is None
    assert fake_client.classification_calls == [b"fake-image"]


def test_ddddocr_solver_returns_slider_offset() -> None:
    fake_client = FakeDdddOcrClient()
    solver = DdddOcrCaptchaSolver(ocr_client=fake_client)

    solution = solver.solve_slider(
        CaptchaChallenge(
            kind="slider_captcha",
            image_bytes=b"background-image",
            puzzle_bytes=b"slider-piece",
        )
    )

    assert solution.offset_x == 42
    assert solution.text is None
    assert fake_client.slide_match_calls == [(b"slider-piece", b"background-image")]


def test_sms_captcha_is_reserved_but_not_implemented() -> None:
    solver = DdddOcrCaptchaSolver(ocr_client=FakeDdddOcrClient())

    with pytest.raises(CaptchaNotImplementedError):
        solver.solve_sms(CaptchaChallenge(kind="sms_captcha"))


def test_solver_is_disabled_when_ddddocr_flag_is_false() -> None:
    solver = build_captcha_solver(settings=Settings(ddddocr_enabled=False))

    with pytest.raises(CaptchaDisabledError):
        solver.solve_image(CaptchaChallenge(kind="image_captcha", image_bytes=b"fake-image"))
