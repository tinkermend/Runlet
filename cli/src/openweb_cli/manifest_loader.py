from __future__ import annotations

from pathlib import Path

import yaml

from openweb_cli.backend_bootstrap import load_web_system_manifest_model


def load_manifest_from_file(path: str | Path):
    manifest_path = Path(path)
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    web_system_manifest = load_web_system_manifest_model()
    return web_system_manifest.model_validate(payload)


def resolve_remove_system_code(
    *,
    file: str | Path | None,
    system_code: str | None,
) -> str:
    normalized_system_code = system_code.strip() if system_code is not None else None
    if file is not None and normalized_system_code:
        raise ValueError("remove 只能提供 --file 或 --system-code 其中之一")

    if normalized_system_code:
        return normalized_system_code

    if file is not None:
        return load_manifest_from_file(file).system.code

    raise ValueError("remove 必须提供 --file 或 --system-code 之一")
