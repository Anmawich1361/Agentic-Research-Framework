from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, cast

import typer

from agentic_research.artifact_review import build_artifact_review, write_artifact_review
from agentic_research.models import CheckpointAnswer, UserFeedback
from agentic_research.orchestrator import (
    continue_research,
    load_user_feedback,
    merge_user_feedback,
    run_research,
    save_user_feedback,
)
from agentic_research.settings import get_artifact_dir


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


def _resolve_run_dir(run_id_or_path: str) -> Path:
    candidate = Path(run_id_or_path)
    if candidate.exists() or candidate.is_absolute() or "/" in run_id_or_path:
        return candidate
    return get_artifact_dir() / run_id_or_path


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_checkpoint_answers(answer_values: list[str]) -> list[CheckpointAnswer]:
    answers: list[CheckpointAnswer] = []
    for value in answer_values:
        if "=" not in value:
            raise typer.BadParameter("--answer must use QUESTION=ANSWER")
        question, answer = value.split("=", 1)
        question = question.strip()
        answer = answer.strip()
        if not question or not answer:
            raise typer.BadParameter("--answer must include a non-empty question and answer")
        answers.append(CheckpointAnswer(question=question, answer=answer))
    return answers


def _feedback_update(
    *,
    answers: list[str] | None = None,
    approved_source_ids: list[str] | None = None,
    rejected_source_ids: list[str] | None = None,
    depth_override: str | None = None,
    lens_override: str | None = None,
    user_notes: str | None = None,
    priority_topics: list[str] | None = None,
) -> UserFeedback:
    try:
        return UserFeedback(
            answered_checkpoint_questions=_parse_checkpoint_answers(answers or []),
            approved_source_ids=approved_source_ids or [],
            rejected_source_ids=rejected_source_ids or [],
            depth_override=cast(Any, depth_override),
            lens_override=cast(Any, lens_override),
            user_notes=user_notes,
            priority_topics=priority_topics or [],
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command("runs")
def runs_command() -> None:
    """List saved research runs."""
    root = get_artifact_dir()
    if not root.exists():
        typer.echo("No runs found.")
        return

    run_dirs = sorted(
        [path for path in root.iterdir() if path.is_dir()],
        key=lambda path: path.name,
        reverse=True,
    )
    if not run_dirs:
        typer.echo("No runs found.")
        return

    for run_dir in run_dirs:
        metadata_path = run_dir / "metadata.json"
        if not metadata_path.exists():
            typer.echo(f"{run_dir.name}\tstatus=unknown")
            continue
        metadata = _load_json(metadata_path)
        typer.echo(
            f"{metadata.get('run_id', run_dir.name)}\t"
            f"status={metadata.get('status', 'unknown')}\t"
            f"lens={metadata.get('lens', 'unknown')}\t"
            f"mock={metadata.get('mock', 'unknown')}\t"
            f"{metadata.get('request', '')}"
        )


@app.command("show")
def show_command(
    run_id_or_path: Annotated[
        str,
        typer.Argument(help="Run ID under runs/ or direct path to a run directory."),
    ],
) -> None:
    """Show saved artifacts for one run."""
    run_dir = _resolve_run_dir(run_id_or_path)
    if not run_dir.exists() or not run_dir.is_dir():
        raise typer.BadParameter(f"Run directory not found: {run_dir}")

    metadata_path = run_dir / "metadata.json"
    metadata = _load_json(metadata_path) if metadata_path.exists() else {}
    typer.echo(f"run_id: {metadata.get('run_id', run_dir.name)}")
    typer.echo(f"status: {metadata.get('status', 'unknown')}")
    typer.echo(f"request: {metadata.get('request', '')}")
    typer.echo(f"run_dir: {run_dir}")
    for artifact_name in [
        "checkpoint.md",
        "user_feedback.json",
        "source_map.json",
        "source_content.json",
        "evidence_ledger.json",
        "draft_report.md",
        "qa_review.json",
        "report.md",
        "artifact_review.md",
    ]:
        status = "present" if (run_dir / artifact_name).exists() else "missing"
        typer.echo(f"{artifact_name}: {status}")


@app.command("add-feedback")
def add_feedback_command(
    run_id_or_path: Annotated[
        str,
        typer.Argument(help="Run ID under runs/ or direct path to a run directory."),
    ],
    answers: Annotated[
        list[str] | None,
        typer.Option("--answer", help="Checkpoint answer as QUESTION=ANSWER. Repeatable."),
    ] = None,
    approved_source_ids: Annotated[
        list[str] | None,
        typer.Option("--approve-source", help="Source ID to approve. Repeatable."),
    ] = None,
    rejected_source_ids: Annotated[
        list[str] | None,
        typer.Option("--reject-source", help="Source ID to reject. Repeatable."),
    ] = None,
    depth_override: Annotated[
        str | None,
        typer.Option("--depth-override", help="Override depth: brief, standard, deep_dive."),
    ] = None,
    lens_override: Annotated[
        str | None,
        typer.Option("--lens-override", help="Override research lens."),
    ] = None,
    user_notes: Annotated[
        str | None,
        typer.Option("--note", help="Free-form user note for continuation."),
    ] = None,
    priority_topics: Annotated[
        list[str] | None,
        typer.Option("--priority-topic", help="Priority topic to emphasize. Repeatable."),
    ] = None,
) -> None:
    """Append checkpoint feedback to a run."""
    run_dir = _resolve_run_dir(run_id_or_path)
    if not run_dir.exists() or not run_dir.is_dir():
        raise typer.BadParameter(f"Run directory not found: {run_dir}")

    updates = _feedback_update(
        answers=answers,
        approved_source_ids=approved_source_ids,
        rejected_source_ids=rejected_source_ids,
        depth_override=depth_override,
        lens_override=lens_override,
        user_notes=user_notes,
        priority_topics=priority_topics,
    )
    feedback = merge_user_feedback(load_user_feedback(run_dir), updates)
    path = save_user_feedback(run_dir, feedback)
    typer.echo(f"user_feedback: {path}")


@app.command("approve-sources")
def approve_sources_command(
    run_id_or_path: Annotated[
        str,
        typer.Argument(help="Run ID under runs/ or direct path to a run directory."),
    ],
    source_ids: Annotated[list[str], typer.Argument(help="Source IDs to approve.")],
) -> None:
    """Approve a source subset for continuation."""
    run_dir = _resolve_run_dir(run_id_or_path)
    if not run_dir.exists() or not run_dir.is_dir():
        raise typer.BadParameter(f"Run directory not found: {run_dir}")
    updates = UserFeedback(approved_source_ids=source_ids)
    feedback = merge_user_feedback(load_user_feedback(run_dir), updates)
    path = save_user_feedback(run_dir, feedback)
    typer.echo(f"user_feedback: {path}")


@app.command("continue")
def continue_command(
    run_id_or_path: Annotated[
        str,
        typer.Argument(help="Run ID under runs/ or direct path to a run directory."),
    ],
    qa: Annotated[
        bool,
        typer.Option("--qa", help="Run QA/red-team review after draft report generation."),
    ] = False,
    mock: Annotated[
        bool,
        typer.Option("--mock", help="Force mock continuation regardless of original run."),
    ] = False,
    live: Annotated[
        bool,
        typer.Option("--live", help="Force live continuation regardless of original run."),
    ] = False,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Optional OpenAI model override for live agent mode."),
    ] = None,
) -> None:
    """Continue a checkpointed run with saved user feedback."""
    if mock and live:
        raise typer.BadParameter("Use only one of --mock or --live.")
    mock_override = True if mock else False if live else None
    try:
        result = continue_research(
            run_id_or_path,
            qa=qa,
            mock=mock_override,
            model=model,
        )
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo(f"run_id: {result.metadata.run_id}")
    typer.echo(f"status: {result.metadata.status}")
    typer.echo(f"checkpoint: {result.checkpoint_path}")
    if result.draft_report_path is not None:
        typer.echo(f"draft_report: {result.draft_report_path}")
    if result.report_path is not None:
        typer.echo(f"report: {result.report_path}")
    elif result.report is not None:
        typer.echo("report: blocked or not requested")


@app.command("review-run")
def review_run_command(
    run_id_or_path: Annotated[
        str,
        typer.Argument(help="Run ID under runs/ or direct path to a run directory."),
    ],
) -> None:
    run_dir = _resolve_run_dir(run_id_or_path)
    if not run_dir.exists() or not run_dir.is_dir():
        raise typer.BadParameter(f"Run directory not found: {run_dir}")
    path = write_artifact_review(run_dir)
    review = build_artifact_review(run_dir)
    typer.echo(f"artifact_review: {path}")
    final_published = "yes" if review.final_report_published else "no"
    typer.echo(f"status: {review.status}")
    typer.echo(f"publication_state: {review.publication_state}")
    typer.echo(f"final_report_published: {final_published}")
    typer.echo(
        "qa_issues: "
        f"high={review.qa_high_count} "
        f"medium={review.qa_medium_count} "
        f"low={review.qa_low_count}"
    )
    typer.echo(
        "source_fetches: "
        f"fetched={review.source_fetch_fetched_count} "
        f"fallback={review.source_fetch_fallback_count} "
        f"failed={review.source_fetch_failed_count} "
        f"skipped={review.source_fetch_skipped_count}"
    )
    if review.blocking_warnings:
        typer.echo("blocking_warnings:")
        for warning in review.blocking_warnings:
            typer.echo(f"- {warning}")
    typer.echo(f"next_action: {review.next_recommended_action}")


if __name__ == "__main__":
    app()
