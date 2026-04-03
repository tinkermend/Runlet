from __future__ import annotations

import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def ensure_backend_src_path() -> Path:
    backend_src = _repo_root() / "backend" / "src"
    if not backend_src.exists():
        raise RuntimeError(f"backend src not found: {backend_src}")

    backend_src_str = str(backend_src)
    if backend_src_str not in sys.path:
        sys.path.insert(0, backend_src_str)
    return backend_src


def load_web_system_manifest_model():
    ensure_backend_src_path()
    from app.domains.control_plane.system_admin_schemas import WebSystemManifest

    return WebSystemManifest


def bootstrap_system_admin_service():
    ensure_backend_src_path()
    from app.domains.control_plane.system_admin_bootstrap import (
        bootstrap_system_admin_service as _bootstrap_system_admin_service,
    )

    return _bootstrap_system_admin_service()
