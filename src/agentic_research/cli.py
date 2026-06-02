from __future__ import annotations

import json
import webbrowser
from pathlib import Path
from typing import Annotated, Any, cast

import typer
from dotenv import load_dotenv

from agentic_research.artifact_review import build_artifact_review, write_artifact_review
from agentic_research.models import CheckpointAnswer, ResearchPlan, SourceMap, UserFeedback
from agentic_research.orchestrator import (
    continue_research,
    load_user_feedback,
    merge_user_feedback,
    run_research,
    save_user_feedback,
)
from agentic_research.settings import PROJECT_ROOT, get_artifact_dir


app = typer.Typer(help="Agentic Research Framework CLI.")
LENS_CHOICES = ["investment", "sales", "strategy", "industry", "general"]
MODE_CHOICES = ["brief", "standard", "deep_dive"]
RUN_PATH_CHOICES = [
    "guided checkpoint to report",
    "checkpoint only",
    "direct full QA report",
]


@app.callback()
def main() -> None:
    """Top-level CLI group."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)


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


def _prompt_choice(prompt: str, choices: list[str], *, default: str) -> str:
    if default not in choices:
        raise ValueError(f"Default choice is not valid: {default}")
    for index, choice in enumerate(choices, start=1):
        typer.echo(f"{index}. {choice}")
    default_index = choices.index(default) + 1
    raw_choice = typer.prompt(prompt, default=str(default_index)).strip()
    if raw_choice in choices:
        return raw_choice
    try:
        selected_index = int(raw_choice)
    except ValueError as exc:
        raise typer.BadParameter(
            f"{prompt} must be a number from 1 to {len(choices)} or one of: "
            f"{', '.join(choices)}"
        ) from exc
    if not 1 <= selected_index <= len(choices):
        raise typer.BadParameter(f"{prompt} must be a number from 1 to {len(choices)}")
    return choices[selected_index - 1]


def _looks_like_full_research_request(value: str) -> bool:
    return value.strip().lower().startswith("research ")


def _wizard_request() -> str:
    target_or_request = typer.prompt("Company/topic or full request").strip()
    if not target_or_request:
        raise typer.BadParameter("Company/topic or full request cannot be empty.")
    if _looks_like_full_research_request(target_or_request):
        return target_or_request
    context = typer.prompt("Preparation context", default="a meeting").strip()
    if not context:
        raise typer.BadParameter("Preparation context cannot be empty.")
    return f"Research {target_or_request} before {context}"


def _print_wizard_result(
    result: Any,
    *,
    checkpoint_first: bool,
    user_feedback_path: Path | None = None,
    opened_report_path: Path | None = None,
    report_open_failed: bool = False,
    continue_next_step: bool = False,
) -> None:
    run_id = result.metadata.run_id
    typer.echo(f"run_id: {run_id}")
    typer.echo(f"status: {result.metadata.status}")
    typer.echo(f"checkpoint: {result.checkpoint_path}")
    if user_feedback_path is not None:
        typer.echo(f"user_feedback: {user_feedback_path}")
    if getattr(result, "draft_report_path", None) is not None:
        typer.echo(f"draft_report: {result.draft_report_path}")
    if getattr(result, "report_path", None) is not None:
        typer.echo(f"report: {result.report_path}")
    if opened_report_path is not None:
        typer.echo(f"opened_report: {opened_report_path}")
    elif report_open_failed:
        typer.echo("opened_report: failed")
    typer.echo(f"run_dir: {result.run_dir}")
    typer.echo(f"next_show: .venv/bin/arf show {run_id}")
    typer.echo(f"next_review: .venv/bin/arf review-run {run_id}")
    if checkpoint_first:
        typer.echo(f"next_approve: .venv/bin/arf approve-sources {run_id} <source_id...>")
        typer.echo(f"next_continue: .venv/bin/arf continue {run_id} --qa")
    elif continue_next_step:
        typer.echo(f"next_continue: .venv/bin/arf continue {run_id} --qa")


def _load_research_plan(run_dir: Path) -> ResearchPlan:
    return ResearchPlan.model_validate(_load_json(run_dir / "research_plan.json"))


def _load_source_map(run_dir: Path) -> SourceMap:
    return SourceMap.model_validate(_load_json(run_dir / "source_map.json"))


def _source_score_lookup(source_map: SourceMap) -> dict[str, float]:
    return {score.source_id: score.final_score for score in source_map.scores}


def _recommended_source_ids(source_map: SourceMap) -> list[str]:
    included_ids = {score.source_id for score in source_map.scores if score.include}
    recommended_ids = [source.id for source in source_map.sources if source.id in included_ids]
    if recommended_ids:
        return recommended_ids
    return [source.id for source in source_map.sources]


def _unique_ordered(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            unique_values.append(value)
    return unique_values


def _parse_source_selection(raw_value: str, source_map: SourceMap) -> list[str]:
    normalized = raw_value.strip().lower()
    if normalized == "recommended":
        return _recommended_source_ids(source_map)
    if normalized == "all":
        return [source.id for source in source_map.sources]
    if normalized == "none":
        return []

    selected_ids: list[str] = []
    source_ids = {source.id for source in source_map.sources}
    for token in raw_value.replace(",", " ").split():
        if token.isdigit():
            source_index = int(token)
            if not 1 <= source_index <= len(source_map.sources):
                raise typer.BadParameter(
                    f"Source number must be between 1 and {len(source_map.sources)}"
                )
            selected_ids.append(source_map.sources[source_index - 1].id)
        elif token in source_ids:
            selected_ids.append(token)
        else:
            raise typer.BadParameter(f"Unknown source selection: {token}")
    return _unique_ordered(selected_ids)


def _prompt_checkpoint_answers(plan: ResearchPlan) -> list[CheckpointAnswer]:
    answers: list[CheckpointAnswer] = []
    if not plan.checkpoint_questions:
        typer.echo("checkpoint_questions: none")
        return answers

    typer.echo("checkpoint_questions:")
    for question in plan.checkpoint_questions:
        answer = typer.prompt(question, default="", show_default=False).strip()
        if answer:
            answers.append(CheckpointAnswer(question=question, answer=answer))
    return answers


def _prompt_approved_source_ids(source_map: SourceMap) -> list[str]:
    if not source_map.sources:
        typer.echo("sources: none")
        return []

    typer.echo("sources:")
    scores = _source_score_lookup(source_map)
    for index, source in enumerate(source_map.sources, start=1):
        score = scores.get(source.id)
        score_text = f", score={score:g}" if score is not None else ""
        typer.echo(
            f"{index}. {source.id} | {source.title} | {source.publisher} | "
            f"{source.source_type}{score_text}"
        )
    raw_selection = typer.prompt(
        "Approved sources",
        default="recommended",
    )
    return _parse_source_selection(raw_selection, source_map)


def _collect_wizard_feedback(run_dir: Path) -> Path:
    plan = _load_research_plan(run_dir)
    source_map = _load_source_map(run_dir)
    answers = _prompt_checkpoint_answers(plan)
    approved_source_ids = _prompt_approved_source_ids(source_map)
    user_notes = typer.prompt("Optional note", default="", show_default=False).strip()
    updates = UserFeedback(
        answered_checkpoint_questions=answers,
        approved_source_ids=approved_source_ids,
        user_notes=user_notes or None,
    )
    feedback = merge_user_feedback(load_user_feedback(run_dir), updates)
    return save_user_feedback(run_dir, feedback)


def _open_report_path(path: Path) -> bool:
    try:
        return bool(webbrowser.open(path.resolve().as_uri()))
    except Exception:
        return False


def _maybe_open_report(result: Any, *, open_report: bool) -> tuple[Path | None, bool]:
    report_path = getattr(result, "report_path", None)
    if not open_report or result.metadata.status != "report_ready" or report_path is None:
        return None, False
    if not Path(report_path).exists():
        return None, True
    return (report_path, False) if _open_report_path(report_path) else (None, True)


@app.command("wizard")
def wizard_command(
    mock: Annotated[bool, typer.Option("--mock", help="Run without live API calls.")] = False,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Optional OpenAI model override for live agent mode."),
    ] = None,
    open_report: Annotated[
        bool,
        typer.Option("--open/--no-open", help="Open report.md when the wizard publishes one."),
    ] = True,
) -> None:
    """Interactively run a new research workflow."""
    request = _wizard_request()
    lens = _prompt_choice("Lens", LENS_CHOICES, default="investment")
    mode = _prompt_choice("Mode", MODE_CHOICES, default="standard")
    run_path = _prompt_choice(
        "Run path",
        RUN_PATH_CHOICES,
        default="guided checkpoint to report",
    )
    try:
        if run_path == "direct full QA report":
            result = run_research(
                request,
                mode=mode,
                lens=lens,
                checkpoint_only=False,
                full=True,
                qa=True,
                mock=mock,
                model=model,
            )
            opened_report_path, report_open_failed = _maybe_open_report(
                result,
                open_report=open_report,
            )
            _print_wizard_result(
                result,
                checkpoint_first=False,
                opened_report_path=opened_report_path,
                report_open_failed=report_open_failed,
                continue_next_step=result.metadata.status != "report_ready",
            )
            return

        checkpoint_result = run_research(
            request,
            mode=mode,
            lens=lens,
            checkpoint_only=True,
            full=False,
            qa=False,
            mock=mock,
            model=model,
        )
        if run_path == "checkpoint only":
            _print_wizard_result(checkpoint_result, checkpoint_first=True)
            return

        feedback_path = _collect_wizard_feedback(checkpoint_result.run_dir)
        result = continue_research(
            checkpoint_result.run_dir,
            qa=True,
            mock=mock,
            model=model,
        )
        opened_report_path, report_open_failed = _maybe_open_report(
            result,
            open_report=open_report,
        )
    except (FileNotFoundError, NotImplementedError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _print_wizard_result(
        result,
        checkpoint_first=False,
        user_feedback_path=feedback_path,
        opened_report_path=opened_report_path,
        report_open_failed=report_open_failed,
        continue_next_step=result.metadata.status != "report_ready",
    )


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
