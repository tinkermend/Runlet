from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLI_SRC = ROOT / "cli" / "src"
BACKEND_SRC = ROOT / "backend" / "src"

for entry in (str(CLI_SRC), str(BACKEND_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from typer.testing import CliRunner

from openweb_cli.main import app
from openweb_cli.manifest_loader import load_manifest_from_file, resolve_remove_system_code


def build_manifest_yaml(system_code: str = "hotgo_test3") -> str:
    return f"""
system:
  code: {system_code}
  name: HotGo
  base_url: https://hotgo.facms.cn
  framework_type: react
credential:
  login_url: https://hotgo.facms.cn/admin#/login?redirect=/dashboard
  username: admin
  password: "123456"
  auth_type: image_captcha
  selectors:
    username: input[name=username]
    password: input[name=password]
    submit: button[type=submit]
auth_policy:
  enabled: true
  schedule_expr: "*/30 * * * *"
  auth_mode: image_captcha
  captcha_provider: ddddocr
crawl_policy:
  enabled: true
  schedule_expr: "0 */2 * * *"
  crawl_scope: full
publish:
  check_goal: table_render
  schedule_expr: "*/30 * * * *"
  enabled: true
"""


def test_load_manifest_from_file_returns_validated_manifest(tmp_path: Path) -> None:
    manifest_path = tmp_path / "hotgo.yaml"
    manifest_path.write_text(build_manifest_yaml(), encoding="utf-8")

    manifest = load_manifest_from_file(manifest_path)

    assert manifest.system.code == "hotgo_test3"
    assert manifest.credential.username == "admin"
    assert manifest.publish.check_goal == "table_render"


def test_resolve_remove_system_code_reads_target_from_manifest_file(tmp_path: Path) -> None:
    manifest_path = tmp_path / "remove.yaml"
    manifest_path.write_text(build_manifest_yaml(system_code="vben_test1"), encoding="utf-8")

    system_code = resolve_remove_system_code(file=manifest_path, system_code=None)

    assert system_code == "vben_test1"


def test_resolve_remove_system_code_rejects_missing_locator() -> None:
    with pytest.raises(ValueError, match="--file 或 --system-code"):
        resolve_remove_system_code(file=None, system_code=None)


def test_web_system_add_invokes_backend_service(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    manifest = SimpleNamespace(system=SimpleNamespace(code="hotgo_test3"))
    result_payload = SimpleNamespace(
        system_code="hotgo_test3",
        system_id=uuid4(),
        page_check_id=uuid4(),
        published_job_id=uuid4(),
        scheduler_job_ids=["auth_policy:job", "crawl_policy:job"],
    )
    calls: dict[str, object] = {}

    class StubService:
        async def onboard_system(self, *, manifest) -> object:
            calls["manifest"] = manifest
            return result_payload

    @asynccontextmanager
    async def fake_bootstrap():
        yield StubService()

    monkeypatch.setattr("openweb_cli.main.load_manifest_from_file", lambda path: manifest)
    monkeypatch.setattr(
        "openweb_cli.main.bootstrap_system_admin_service",
        lambda: fake_bootstrap(),
    )

    result = runner.invoke(app, ["web-system", "add", "--file", "/tmp/hotgo.yaml"])

    assert result.exit_code == 0
    assert calls["manifest"] is manifest
    assert "接入完成" in result.stdout
    assert "system_code=hotgo_test3" in result.stdout


def test_web_system_remove_requires_locator() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["web-system", "remove"])

    assert result.exit_code != 0
    combined_output = result.stdout + getattr(result, "stderr", "")
    assert "--file 或 --system-code" in combined_output


def test_web_system_remove_invokes_backend_service(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    result_payload = SimpleNamespace(
        system_found=True,
        remaining_scheduler_job_ids=[],
        remaining_reference_tables=[],
    )
    calls: dict[str, object] = {}

    class StubService:
        async def teardown_system(self, *, system_code: str) -> object:
            calls["system_code"] = system_code
            return result_payload

    @asynccontextmanager
    async def fake_bootstrap():
        yield StubService()

    monkeypatch.setattr(
        "openweb_cli.main.resolve_remove_system_code",
        lambda *, file, system_code: system_code or "ignored",
    )
    monkeypatch.setattr(
        "openweb_cli.main.bootstrap_system_admin_service",
        lambda: fake_bootstrap(),
    )

    result = runner.invoke(app, ["web-system", "remove", "--system-code", "vben_test1"])

    assert result.exit_code == 0
    assert calls["system_code"] == "vben_test1"
    assert "删除完成" in result.stdout
    assert "system_code=vben_test1" in result.stdout
