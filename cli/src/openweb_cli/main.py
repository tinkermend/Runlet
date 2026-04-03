from __future__ import annotations

from pathlib import Path

import anyio
import typer

from openweb_cli.backend_bootstrap import bootstrap_system_admin_service
from openweb_cli.manifest_loader import (
    load_manifest_from_file,
    resolve_remove_system_code,
)

app = typer.Typer()
web_system_app = typer.Typer(help="Web 测试系统接入与删除命令。")


async def _onboard_web_system(manifest):
    async with bootstrap_system_admin_service() as service:
        return await service.onboard_system(manifest=manifest)


async def _teardown_web_system(system_code: str):
    async with bootstrap_system_admin_service() as service:
        return await service.teardown_system(system_code=system_code)


def _format_values(values: list[str]) -> str:
    return ",".join(values) if values else "-"


@app.callback()
def main() -> None:
    """OpenWeb CLI command group."""


@app.command("doctor")
def doctor() -> None:
    typer.echo("ok")


@web_system_app.command("add")
def add_web_system(
    file: Path = typer.Option(..., "--file", dir_okay=False, help="YAML 清单路径。"),
) -> None:
    manifest = load_manifest_from_file(file)
    result = anyio.run(_onboard_web_system, manifest)
    typer.echo("接入完成")
    typer.echo(f"system_code={result.system_code}")
    typer.echo(f"system_id={result.system_id}")
    typer.echo(f"page_check_id={result.page_check_id}")
    typer.echo(f"published_job_id={result.published_job_id}")
    typer.echo(f"scheduler_job_ids={_format_values(result.scheduler_job_ids)}")


@web_system_app.command("remove")
def remove_web_system(
    file: Path | None = typer.Option(
        None,
        "--file",
        dir_okay=False,
        help="YAML 清单路径。",
    ),
    system_code: str | None = typer.Option(
        None,
        "--system-code",
        help="直接指定要删除的系统编码。",
    ),
) -> None:
    try:
        target_system_code = resolve_remove_system_code(file=file, system_code=system_code)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    result = anyio.run(_teardown_web_system, target_system_code)
    typer.echo("删除完成" if result.system_found else "系统不存在，无需删除")
    typer.echo(f"system_code={target_system_code}")
    typer.echo(
        "remaining_scheduler_job_ids="
        f"{_format_values(result.remaining_scheduler_job_ids)}"
    )
    typer.echo(
        "remaining_reference_tables="
        f"{_format_values(result.remaining_reference_tables)}"
    )


app.add_typer(web_system_app, name="web-system")


if __name__ == "__main__":
    app()
