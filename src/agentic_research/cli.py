from __future__ import annotations

from typing import Annotated

import typer

from agentic_research.orchestrator import run_research


app = typer.Typer(help="Agentic Research Framework CLI.")


@app.callback()
def main() -> None:
    """Top-level CLI group."""


@app.command("run")
def run_command(
    request: Annotated[str, typer.Argument(help="Research request to run.")],
    mock: Annotated[bool, typer.Option("--mock", help="Run without live API calls.")] = False,
    checkpoint_only: Annotated[
        bool,
        typer.Option("--checkpoint-only", help="Stop after writing the user checkpoint."),
    ] = False,
    full: Annotated[
        bool,
        typer.Option("--full", help="Run through evidence extraction and report generation."),
    ] = False,
    qa: Annotated[
        bool,
        typer.Option("--qa", help="Run QA/red-team review after draft report generation."),
    ] = False,
    mode: Annotated[str, typer.Option("--mode", help="Research depth mode.")] = "standard",
    lens: Annotated[str | None, typer.Option("--lens", help="Optional research lens override.")] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Optional OpenAI model override for live agent mode."),
    ] = None,
) -> None:
    try:
        result = run_research(
            request,
            mode=mode,
            lens=lens,
            checkpoint_only=checkpoint_only,
            full=full,
            qa=qa,
            mock=mock,
            model=model,
        )
    except NotImplementedError as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo(f"run_id: {result.metadata.run_id}")
    typer.echo(f"checkpoint: {result.checkpoint_path}")


if __name__ == "__main__":
    app()
