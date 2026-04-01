import typer

app = typer.Typer()


@app.callback()
def main() -> None:
    """OpenWeb CLI command group."""


@app.command("doctor")
def doctor() -> None:
    typer.echo("ok")


if __name__ == "__main__":
    app()
