from __future__ import annotations

import re


_PLACEHOLDER_PATTERN = re.compile(r"^\{\{\s*([a-zA-Z0-9_]+)\s*\}\}$")


def resolve_template_placeholders(
    *,
    params: dict[str, object],
    runtime_inputs: dict[str, object] | None,
) -> dict[str, object]:
    if not params:
        return {}
    if not runtime_inputs:
        return dict(params)

    resolved: dict[str, object] = {}
    for key, value in params.items():
        resolved[key] = _resolve_value(value=value, runtime_inputs=runtime_inputs)
    return resolved


def coerce_optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if normalized and normalized.lstrip("-").isdigit():
            return int(normalized)
    return None


def validate_data_count_assertion(
    *,
    count: int,
    expected_min: int | None,
    expected_max: int | None,
) -> None:
    if expected_min is not None and count < expected_min:
        raise ValueError(
            f"data_count_assertion_failed: expected at least {expected_min}, got {count}"
        )
    if expected_max is not None and count > expected_max:
        raise ValueError(
            f"data_count_assertion_failed: expected at most {expected_max}, got {count}"
        )


def _resolve_value(*, value: object, runtime_inputs: dict[str, object]) -> object:
    if not isinstance(value, str):
        return value
    matched = _PLACEHOLDER_PATTERN.match(value.strip())
    if matched is None:
        return value
    key = matched.group(1)
    if key not in runtime_inputs:
        return value
    return runtime_inputs[key]
