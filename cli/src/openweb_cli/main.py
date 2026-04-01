import typer

app = typer.Typer()


@app.command("doctor")
def doctor() -> None:
    typer.echo("ok")


if __name__ == "__main__":
    app()
