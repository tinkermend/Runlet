from __future__ import annotations

from typing import Any, Protocol

from app.config.settings import Settings
from app.domains.auth_service.schemas import CaptchaChallenge, CaptchaSolution


class CaptchaSolverError(RuntimeError):
    pass


class CaptchaDisabledError(CaptchaSolverError):
    pass


class CaptchaNotImplementedError(CaptchaSolverError):
    pass


class CaptchaSolveError(CaptchaSolverError):
    pass


class CaptchaSolver(Protocol):
    def solve_image(self, challenge: CaptchaChallenge) -> CaptchaSolution: ...

    def solve_slider(self, challenge: CaptchaChallenge) -> CaptchaSolution: ...

    def solve_sms(self, challenge: CaptchaChallenge) -> CaptchaSolution: ...


class DisabledCaptchaSolver:
    def solve_image(self, challenge: CaptchaChallenge) -> CaptchaSolution:
        del challenge
        raise CaptchaDisabledError("ddddocr captcha solver is disabled")

    def solve_slider(self, challenge: CaptchaChallenge) -> CaptchaSolution:
        del challenge
        raise CaptchaDisabledError("ddddocr captcha solver is disabled")

    def solve_sms(self, challenge: CaptchaChallenge) -> CaptchaSolution:
        del challenge
        raise CaptchaNotImplementedError("sms captcha solver is reserved but not implemented")


class DdddOcrCaptchaSolver:
    def __init__(
        self,
        *,
        ocr_client: object | None = None,
        slider_client: object | None = None,
    ) -> None:
        self._ocr_client = ocr_client
        self._slider_client = slider_client or ocr_client

    def solve_image(self, challenge: CaptchaChallenge) -> CaptchaSolution:
        if challenge.image_bytes is None:
            raise CaptchaSolveError("image captcha requires image_bytes")
        client = self._get_ocr_client()
        text = client.classification(challenge.image_bytes)
        return CaptchaSolution(kind=challenge.kind, text=str(text))

    def solve_slider(self, challenge: CaptchaChallenge) -> CaptchaSolution:
        if challenge.image_bytes is None or challenge.puzzle_bytes is None:
            raise CaptchaSolveError("slider captcha requires image_bytes and puzzle_bytes")
        client = self._get_slider_client()
        raw_result = client.slide_match(challenge.puzzle_bytes, challenge.image_bytes)
        offset_x = self._extract_offset_x(raw_result)
        return CaptchaSolution(kind=challenge.kind, offset_x=offset_x)

    def solve_sms(self, challenge: CaptchaChallenge) -> CaptchaSolution:
        del challenge
        raise CaptchaNotImplementedError("sms captcha solver is reserved but not implemented")

    def _get_ocr_client(self) -> Any:
        if self._ocr_client is None:
            self._ocr_client = self._build_default_client(slider=False)
        return self._ocr_client

    def _get_slider_client(self) -> Any:
        if self._slider_client is None:
            self._slider_client = self._build_default_client(slider=True)
        return self._slider_client

    def _build_default_client(self, *, slider: bool) -> Any:
        try:
            import ddddocr
        except ModuleNotFoundError as exc:
            raise CaptchaDisabledError("ddddocr is not installed") from exc

        if slider:
            return ddddocr.DdddOcr(det=False, ocr=False)
        return ddddocr.DdddOcr()

    def _extract_offset_x(self, raw_result: object) -> int:
        if isinstance(raw_result, dict):
            target = raw_result.get("target")
            if isinstance(target, list) and target:
                first = target[0]
                if isinstance(first, (int, float)):
                    return int(first)
        raise CaptchaSolveError("ddddocr slider result does not contain a usable target offset")


def build_captcha_solver(
    *,
    settings: Settings,
    ocr_client: object | None = None,
    slider_client: object | None = None,
) -> CaptchaSolver:
    if not settings.ddddocr_enabled:
        return DisabledCaptchaSolver()
    return DdddOcrCaptchaSolver(
        ocr_client=ocr_client,
        slider_client=slider_client,
    )
