from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from agentic_research.artifact_review import write_artifact_review
from agentic_research.models import (
    EvidenceLedger as EvidenceLedgerModel,
    QAReview,
    ResearchCharter,
    ResearchPlan,
    Report,
    RunMetadata,
    RunType,
    SourceCandidate,
    SourceContent,
    SourceFetchLog,
    SourceMap,
    SpecialistAnalysis,
    UserFeedback,
)
from agentic_research.report_validation import ReportSectionValidationError
from agentic_research.report_writer import (
    write_checkpoint,
    write_json_artifact,
    write_report_artifacts,
)
from agentic_research.run_logging import RunLogger


EMPTY_EVIDENCE_WARNING = "No valid evidence claims were extracted from approved sources."


class ResearchRunResult(BaseModel):
    metadata: RunMetadata
    run_dir: Path
    checkpoint_path: Path
    charter: ResearchCharter
    research_plan: ResearchPlan
    sources: list[SourceCandidate]
    source_map: SourceMap
    source_content: list[SourceContent] = Field(default_factory=list)
    source_fetch_log: SourceFetchLog | None = None
    source_discovery_review: dict[str, Any] | None = None
    user_feedback: UserFeedback | None = None
    specialist_analyses: list[SpecialistAnalysis] = Field(default_factory=list)
    evidence_ledger: EvidenceLedgerModel | None = None
    report: Report | None = None
    draft_report_path: Path | None = None
    report_path: Path | None = None
    qa_review: QAReview | None = None


NON_BLOCKING_EVIDENCE_WARNING_PREFIXES = (
    "Deduplicated duplicate evidence claim ID ",
    "Deduplicated near-duplicate evidence claim ID ",
    "Downgraded evidence claim ID ",
    "Dropped unsupported evidence claim ID ",
    "Repaired stale source_url for evidence claim ID ",
    "Renamed conflicting specialist evidence claim ID ",
)


def _status_reason_text(status: str) -> str:
    return {
        "checkpoint_ready": "Checkpoint artifacts written; awaiting user feedback.",
        "evidence_ready": "Evidence ledger written and ready for synthesis.",
        "evidence_needs_review": "Evidence validation produced blocking warnings.",
        "draft_needs_qa": "Draft report written; QA has not approved final publication.",
        "draft_needs_revision": "Draft report failed deterministic report validation.",
        "needs_review": "QA found blocking issues; final report was not written.",
        "report_ready": "QA passed and final report was written.",
        "failed": "Run failed before successful completion.",
    }.get(status, "Run status recorded.")


def duration_seconds(started_at: datetime, completed_at: datetime) -> float:
    return round((completed_at - started_at).total_seconds(), 3)


def status_reason(status: str) -> str:
    return _status_reason_text(status)


def write_logged_json_artifact(
    path: Path,
    value: Any,
    run_logger: RunLogger | None,
) -> None:
    write_json_artifact(path, value)
    if run_logger is not None:
        run_logger.artifact(path)


def write_logged_text_artifact(
    path: Path,
    text: str,
    run_logger: RunLogger | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if run_logger is not None:
        run_logger.artifact(path)


def failure_report_markdown(
    *,
    run_id: str,
    request: str,
    error: BaseException,
) -> str:
    return (
        f"# Run Failure: {run_id}\n\n"
        f"- Request: {request}\n"
        f"- Error type: {type(error).__name__}\n"
        f"- Error message: {error}\n\n"
        "No final report was written for this failed run.\n"
    )


def write_failure_artifacts(
    *,
    run_id: str,
    run_dir: Path,
    request: str,
    mode: str,
    lens: str | None,
    mock: bool,
    model: str | None,
    run_type: RunType,
    started_at: datetime,
    error: BaseException,
    run_logger: RunLogger | None,
) -> None:
    completed_at = datetime.now(timezone.utc)
    failure_status_reason = f"{type(error).__name__}: {error}"
    metadata = RunMetadata(
        run_id=run_id,
        created_at=started_at.isoformat(),
        started_at=started_at.isoformat(),
        completed_at=completed_at.isoformat(),
        duration_seconds=duration_seconds(started_at, completed_at),
        request=request,
        status="failed",
        status_reason=failure_status_reason,
        mode=mode,
        lens=lens or "general",
        mock=mock,
        model=model,
        run_type=run_type,
    )
    write_logged_json_artifact(run_dir / "metadata.json", metadata, run_logger)
    write_logged_json_artifact(
        run_dir / "error.json",
        {
            "error_type": type(error).__name__,
            "message": str(error),
            "status_reason": failure_status_reason,
        },
        run_logger,
    )
    write_logged_text_artifact(
        run_dir / "failure_report.md",
        failure_report_markdown(run_id=run_id, request=request, error=error),
        run_logger,
    )


def write_checkpoint_artifacts(
    *,
    run_id: str,
    run_dir: Path,
    request: str,
    mode: str,
    mock: bool,
    charter: ResearchCharter,
    plan: ResearchPlan,
    sources: list[SourceCandidate],
    source_map: SourceMap,
    source_content: list[SourceContent] | None = None,
    source_fetch_log: SourceFetchLog | None = None,
    source_discovery_review: dict[str, Any] | None = None,
    user_feedback: UserFeedback | None = None,
    specialist_analyses: list[SpecialistAnalysis] | None = None,
    evidence_ledger: EvidenceLedgerModel | None = None,
    report: Report | None = None,
    qa_review: QAReview | None = None,
    write_final_report: bool = True,
    status: str = "checkpoint_ready",
    started_at: datetime | None = None,
    model: str | None = None,
    run_type: RunType = "checkpoint",
    status_reason: str | None = None,
    run_logger: RunLogger | None = None,
) -> ResearchRunResult:
    completed_at = datetime.now(timezone.utc)
    effective_started_at = started_at or completed_at
    metadata = RunMetadata(
        run_id=run_id,
        created_at=effective_started_at.isoformat(),
        started_at=effective_started_at.isoformat(),
        completed_at=completed_at.isoformat(),
        duration_seconds=duration_seconds(effective_started_at, completed_at),
        request=request,
        status=status,
        status_reason=status_reason or _status_reason_text(status),
        mode=mode,
        lens=charter.research_lens,
        mock=mock,
        model=model,
        run_type=run_type,
    )

    write_logged_json_artifact(run_dir / "metadata.json", metadata, run_logger)
    write_logged_json_artifact(run_dir / "charter.json", charter, run_logger)
    write_logged_json_artifact(run_dir / "research_plan.json", plan, run_logger)
    write_logged_json_artifact(run_dir / "sources.json", sources, run_logger)
    write_logged_json_artifact(run_dir / "source_map.json", source_map, run_logger)
    if source_discovery_review is not None:
        write_logged_json_artifact(
            run_dir / "source_discovery_review.json",
            source_discovery_review,
            run_logger,
        )
    if source_content is not None:
        write_logged_json_artifact(run_dir / "source_content.json", source_content, run_logger)
    if source_fetch_log is not None:
        write_logged_json_artifact(
            run_dir / "source_fetch_log.json",
            source_fetch_log,
            run_logger,
        )
    if user_feedback is not None:
        write_logged_json_artifact(run_dir / "user_feedback.json", user_feedback, run_logger)
    if specialist_analyses:
        write_logged_json_artifact(
            run_dir / "specialist_analyses.json",
            specialist_analyses,
            run_logger,
        )
    if evidence_ledger is not None:
        write_logged_json_artifact(
            run_dir / "evidence_ledger.json",
            evidence_ledger,
            run_logger,
        )
    write_evidence_review_artifact(
        run_dir,
        evidence_ledger,
        status=status,
        source_content=source_content,
        source_fetch_log=source_fetch_log,
    )
    draft_report_path = None
    report_path = None
    if report is not None:
        draft_report_path, report_path = write_report_artifacts(
            run_dir,
            report,
            write_final=write_final_report,
        )
        if run_logger is not None:
            run_logger.artifact(draft_report_path)
            if report_path is not None:
                run_logger.artifact(report_path)
    if qa_review is not None:
        write_logged_json_artifact(run_dir / "qa_review.json", qa_review, run_logger)
    checkpoint_path = write_checkpoint(run_dir, charter, plan, source_map, mock=mock)
    if run_logger is not None:
        run_logger.artifact(checkpoint_path)
    if evidence_ledger is not None or report is not None or qa_review is not None:
        artifact_review_path = write_artifact_review(run_dir)
        if run_logger is not None:
            run_logger.artifact(artifact_review_path)

    return ResearchRunResult(
        metadata=metadata,
        run_dir=run_dir,
        checkpoint_path=checkpoint_path,
        charter=charter,
        research_plan=plan,
        sources=sources,
        source_map=source_map,
        source_content=source_content or [],
        source_fetch_log=source_fetch_log,
        source_discovery_review=source_discovery_review,
        user_feedback=user_feedback,
        specialist_analyses=specialist_analyses or [],
        evidence_ledger=evidence_ledger,
        report=report,
        draft_report_path=draft_report_path,
        report_path=report_path,
        qa_review=qa_review,
    )


def is_blocking_evidence_warning(warning: str) -> bool:
    return not warning.startswith(NON_BLOCKING_EVIDENCE_WARNING_PREFIXES)


def has_blocking_evidence_warnings(evidence_ledger: EvidenceLedgerModel) -> bool:
    return any(
        is_blocking_evidence_warning(warning)
        for warning in evidence_ledger.validation_warnings
    )


def _source_fetch_counts(source_fetch_log: SourceFetchLog | None) -> tuple[int, int, int, int]:
    if source_fetch_log is None:
        return 0, 0, 0, 0
    fetched = fallback = failed = skipped = 0
    for result in source_fetch_log.results:
        if result.status == "fetched":
            fetched += 1
        elif result.status == "fallback":
            fallback += 1
        elif result.status == "failed":
            failed += 1
        elif result.status == "skipped":
            skipped += 1
    return fetched, fallback, failed, skipped


def _evidence_sufficiency_lines(
    *,
    evidence_ledger: EvidenceLedgerModel,
    source_content: list[SourceContent] | None,
    source_fetch_log: SourceFetchLog | None,
) -> list[str]:
    if evidence_ledger.claims:
        return []

    fetched_count, fallback_count, failed_count, skipped_count = _source_fetch_counts(
        source_fetch_log
    )
    content_count = len(source_content or [])
    lines = [
        f"- {EMPTY_EVIDENCE_WARNING}",
        "- Inspect source_content.json and source_fetch_log.json before rerunning.",
    ]
    if content_count > 0:
        source_word = "source" if content_count == 1 else "sources"
        lines.append(
            f"- Fetched source content exists for {content_count} {source_word}; "
            "check the evidence extraction prompt/source chunks."
        )
    else:
        lines.append(
            "- No source content was fetched; check source discovery/source ingestion."
        )
    if source_fetch_log is not None:
        lines.append(
            "- Fetch results: "
            f"{fetched_count} fetched, {fallback_count} fallback, "
            f"{failed_count} failed, {skipped_count} skipped."
        )
    return lines


def evidence_review_markdown(
    evidence_ledger: EvidenceLedgerModel,
    *,
    source_content: list[SourceContent] | None = None,
    source_fetch_log: SourceFetchLog | None = None,
) -> str:
    blocking_warnings = [
        warning
        for warning in evidence_ledger.validation_warnings
        if is_blocking_evidence_warning(warning)
    ]
    warning_lines = "\n".join(f"- {warning}" for warning in blocking_warnings)
    sufficiency_lines = _evidence_sufficiency_lines(
        evidence_ledger=evidence_ledger,
        source_content=source_content,
        source_fetch_log=source_fetch_log,
    )
    sufficiency_section = ""
    if sufficiency_lines:
        sufficiency_section = (
            "\n\n## Evidence Sufficiency\n"
            + "\n".join(sufficiency_lines)
            + "\n"
        )
    return (
        "# Evidence Review Required\n\n"
        "Synthesis and QA were skipped because evidence validation produced "
        "blocking warnings. Synthesis and QA were not run, and no final report "
        "was written.\n\n"
        "## Blocking Warnings\n"
        f"{warning_lines or '- None'}\n"
        f"{sufficiency_section}"
    )


def write_evidence_review_artifact(
    run_dir: Path,
    evidence_ledger: EvidenceLedgerModel | None,
    *,
    status: str,
    source_content: list[SourceContent] | None = None,
    source_fetch_log: SourceFetchLog | None = None,
) -> None:
    if (
        status != "evidence_needs_review"
        or evidence_ledger is None
        or not has_blocking_evidence_warnings(evidence_ledger)
    ):
        return
    (run_dir / "evidence_review.md").write_text(
        evidence_review_markdown(
            evidence_ledger,
            source_content=source_content,
            source_fetch_log=source_fetch_log,
        ),
        encoding="utf-8",
    )


def report_revision_markdown(
    *,
    error: ReportSectionValidationError,
    evidence_ledger: EvidenceLedgerModel,
) -> str:
    allowed_claim_lines = "\n".join(
        f"- {claim.id}" for claim in evidence_ledger.claims
    )
    return (
        "# Draft Revision Required\n\n"
        "QA was not run because deterministic pre-QA report validation failed.\n"
        "No final report was written.\n\n"
        "## Validation Error\n"
        f"- {error}\n\n"
        "## Allowed Claim IDs\n"
        f"{allowed_claim_lines or '- None'}\n"
    )


def write_report_revision_artifact(
    run_dir: Path,
    *,
    error: ReportSectionValidationError,
    evidence_ledger: EvidenceLedgerModel,
    run_logger: RunLogger | None = None,
) -> None:
    write_logged_text_artifact(
        run_dir / "report_revision.md",
        report_revision_markdown(error=error, evidence_ledger=evidence_ledger),
        run_logger,
    )
