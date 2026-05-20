from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, cast
from uuid import uuid4

from pydantic import BaseModel, Field

from agentic_research.agents import (
    coerce_agent_output,
    create_agent_set,
    create_mock_charter,
    create_mock_plan,
    discover_mock_sources,
    get_agent_output_type,
    run_agent_sync,
)
from agentic_research.artifact_review import write_artifact_review
from agentic_research.evidence_ledger import (
    EvidenceLedger,
    evidence_claim_content_key,
    raise_if_report_has_unsupported_claims,
)
from agentic_research.evidence_quality import is_near_duplicate_claim
from agentic_research.evidence_quality import classify_evidence_claim
from agentic_research.models import (
    Confidence,
    EvidenceClaim,
    EvidenceExtractionResult,
    EvidenceLedger as EvidenceLedgerModel,
    QAReview,
    ResearchCharter,
    ResearchPlan,
    Report,
    RunMetadata,
    RunType,
    SourceCandidate,
    SourceChunk,
    SourceContent,
    SourceDiscoveryResult,
    SourceFetchLog,
    SourceMap,
    SourceScore,
    SpecialistAnalysis,
    UserFeedback,
)
from agentic_research.report_writer import (
    load_template,
    render_mock_report,
    render_source_appendix,
    select_report_template_name,
    write_checkpoint,
    write_json_artifact,
    write_report_artifacts,
)
from agentic_research.report_validation import (
    ReportSectionValidationError,
    missing_report_sections,
    required_sections_for_report,
    validate_report_sections,
    validate_report_traceability,
)
from agentic_research.run_logging import RunLogger
from agentic_research.qa import (
    has_high_severity_issues,
    merge_qa_reviews,
    run_deterministic_qa_checks,
)
from agentic_research.settings import get_artifact_dir
from agentic_research.source_scoring import build_source_map
from agentic_research.source_ingestion import SourceFetcher, ingest_source_content
from agentic_research.specialists import (
    build_mock_specialist_analyses,
    runnable_specialist_agent_keys,
    select_specialists,
)
from agentic_research.tools.web_search import WebSearchClient, build_source_search_queries


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
    user_feedback: UserFeedback | None = None
    specialist_analyses: list[SpecialistAnalysis] = Field(default_factory=list)
    evidence_ledger: EvidenceLedgerModel | None = None
    report: Report | None = None
    draft_report_path: Path | None = None
    report_path: Path | None = None
    qa_review: QAReview | None = None


AgentRunner = Callable[[str, Any, str], Any]
_NON_BLOCKING_EVIDENCE_WARNING_PREFIXES = (
    "Deduplicated duplicate evidence claim ID ",
    "Deduplicated near-duplicate evidence claim ID ",
    "Downgraded evidence claim ID ",
    "Dropped unsupported evidence claim ID ",
    "Renamed conflicting specialist evidence claim ID ",
)


def _new_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run_{timestamp}_{uuid4().hex[:8]}"


def _json_prompt(title: str, payload: dict[str, Any]) -> str:
    return f"{title}\n\n```json\n{json.dumps(payload, indent=2)}\n```"


def _run_live_agent(
    agent_key: str,
    agent: Any,
    prompt: str,
    *,
    agent_runner: AgentRunner | None,
    run_logger: RunLogger | None = None,
) -> BaseModel:
    runner = agent_runner or (lambda _key, sdk_agent, sdk_prompt: run_agent_sync(sdk_agent, sdk_prompt))
    if run_logger is not None:
        run_logger.agent_call(agent_key, status="start", prompt_chars=len(prompt))
    try:
        output = runner(agent_key, agent, prompt)
        coerced_output = coerce_agent_output(output, get_agent_output_type(agent_key))
    except Exception as exc:
        if run_logger is not None:
            run_logger.error(exc, stage=agent_key)
            run_logger.agent_call(agent_key, status="error", error=str(exc))
        raise
    if run_logger is not None:
        run_logger.agent_call(
            agent_key,
            status="end",
            output_type=type(coerced_output).__name__,
        )
    return coerced_output


def _create_run_dir(runs_dir: str | Path | None) -> tuple[str, Path]:
    run_id = _new_run_id()
    root = Path(runs_dir) if runs_dir is not None else get_artifact_dir()
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_id, run_dir


def _duration_seconds(started_at: datetime, completed_at: datetime) -> float:
    return round((completed_at - started_at).total_seconds(), 3)


def _status_reason(status: str) -> str:
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


def _write_logged_json_artifact(
    path: Path,
    value: Any,
    run_logger: RunLogger | None,
) -> None:
    write_json_artifact(path, value)
    if run_logger is not None:
        run_logger.artifact(path)


def _write_logged_text_artifact(
    path: Path,
    text: str,
    run_logger: RunLogger | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if run_logger is not None:
        run_logger.artifact(path)


def _failure_report_markdown(
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


def _write_failure_artifacts(
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
    status_reason = f"{type(error).__name__}: {error}"
    metadata = RunMetadata(
        run_id=run_id,
        created_at=started_at.isoformat(),
        started_at=started_at.isoformat(),
        completed_at=completed_at.isoformat(),
        duration_seconds=_duration_seconds(started_at, completed_at),
        request=request,
        status="failed",
        status_reason=status_reason,
        mode=mode,
        lens=lens or "general",
        mock=mock,
        model=model,
        run_type=run_type,
    )
    _write_logged_json_artifact(run_dir / "metadata.json", metadata, run_logger)
    _write_logged_json_artifact(
        run_dir / "error.json",
        {
            "error_type": type(error).__name__,
            "message": str(error),
            "status_reason": status_reason,
        },
        run_logger,
    )
    _write_logged_text_artifact(
        run_dir / "failure_report.md",
        _failure_report_markdown(run_id=run_id, request=request, error=error),
        run_logger,
    )


def _resolve_run_dir(run_id_or_path: str | Path, runs_dir: str | Path | None = None) -> Path:
    value = Path(run_id_or_path)
    raw_value = str(run_id_or_path)
    if value.exists() or value.is_absolute() or "/" in raw_value:
        return value
    root = Path(runs_dir) if runs_dir is not None else get_artifact_dir()
    return root / raw_value


def _read_json_artifact(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_model_artifact(path: Path, model_type: type[BaseModel]) -> BaseModel:
    return model_type.model_validate(_read_json_artifact(path))


def load_user_feedback(run_id_or_path: str | Path, runs_dir: str | Path | None = None) -> UserFeedback:
    run_dir = _resolve_run_dir(run_id_or_path, runs_dir)
    feedback_path = run_dir / "user_feedback.json"
    if not feedback_path.exists():
        return UserFeedback()
    return UserFeedback.model_validate(_read_json_artifact(feedback_path))


def save_user_feedback(
    run_id_or_path: str | Path,
    feedback: UserFeedback,
    *,
    runs_dir: str | Path | None = None,
) -> Path:
    run_dir = _resolve_run_dir(run_id_or_path, runs_dir)
    if not run_dir.exists() or not run_dir.is_dir():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")
    feedback_path = run_dir / "user_feedback.json"
    write_json_artifact(feedback_path, feedback)
    return feedback_path


def _unique_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_items: list[str] = []
    for item in items:
        normalized = item.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_items.append(normalized)
    return unique_items


def merge_user_feedback(existing: UserFeedback, updates: UserFeedback) -> UserFeedback:
    user_notes = existing.user_notes
    if updates.user_notes:
        user_notes = (
            f"{user_notes}\n{updates.user_notes}" if user_notes else updates.user_notes
        )
    return UserFeedback(
        answered_checkpoint_questions=[
            *existing.answered_checkpoint_questions,
            *updates.answered_checkpoint_questions,
        ],
        approved_source_ids=_unique_strings(
            [*existing.approved_source_ids, *updates.approved_source_ids]
        ),
        rejected_source_ids=_unique_strings(
            [*existing.rejected_source_ids, *updates.rejected_source_ids]
        ),
        depth_override=updates.depth_override or existing.depth_override,
        lens_override=updates.lens_override or existing.lens_override,
        user_notes=user_notes,
        priority_topics=_unique_strings([*existing.priority_topics, *updates.priority_topics]),
    )


def _charter_with_feedback(charter: ResearchCharter, feedback: UserFeedback) -> ResearchCharter:
    updates: dict[str, Any] = {}
    if feedback.depth_override is not None:
        updates["depth"] = feedback.depth_override
    if feedback.lens_override is not None:
        updates["research_lens"] = feedback.lens_override
    if not updates:
        return charter
    return charter.model_copy(update=updates)


def _source_scores_with_approvals(
    scores: list[SourceScore],
    *,
    approved_source_ids: set[str],
    allowed_source_ids: set[str],
) -> list[SourceScore]:
    updated_scores: list[SourceScore] = []
    for score in scores:
        if score.source_id not in allowed_source_ids:
            continue
        if score.source_id in approved_source_ids:
            updated_scores.append(score.model_copy(update={"include": True}))
        else:
            updated_scores.append(score)
    return updated_scores


def _source_map_with_feedback(source_map: SourceMap, feedback: UserFeedback) -> SourceMap:
    rejected_source_ids = set(feedback.rejected_source_ids)
    known_source_ids = {source.id for source in source_map.sources}
    approved_source_ids = set(feedback.approved_source_ids) & known_source_ids

    if approved_source_ids:
        allowed_source_ids = approved_source_ids - rejected_source_ids
    else:
        allowed_source_ids = known_source_ids - rejected_source_ids

    filtered_sources = [
        source for source in source_map.sources if source.id in allowed_source_ids
    ]
    filtered_scores = _source_scores_with_approvals(
        source_map.scores,
        approved_source_ids=approved_source_ids,
        allowed_source_ids=allowed_source_ids,
    )

    if allowed_source_ids == known_source_ids and not approved_source_ids:
        return source_map

    note_suffix = "User feedback applied before continuation."
    notes = f"{source_map.notes}\n{note_suffix}" if source_map.notes else note_suffix
    return source_map.model_copy(
        update={
            "sources": filtered_sources,
            "scores": filtered_scores,
            "notes": notes,
        }
    )


def _user_feedback_prompt_payload(feedback: UserFeedback) -> dict[str, Any]:
    payload = feedback.model_dump(mode="json")
    rejected_source_ids = set(payload.pop("rejected_source_ids", []))
    payload["approved_source_ids"] = [
        source_id
        for source_id in payload["approved_source_ids"]
        if source_id not in rejected_source_ids
    ]
    rejected_source_count = len(rejected_source_ids)
    payload["rejected_source_count"] = rejected_source_count
    payload["source_filtering_note"] = (
        "Rejected source IDs were removed from source_map before this stage."
        if rejected_source_count
        else "No rejected source IDs were recorded."
    )
    return payload


def _write_checkpoint_artifacts(
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
        duration_seconds=_duration_seconds(effective_started_at, completed_at),
        request=request,
        status=status,
        status_reason=status_reason or _status_reason(status),
        mode=mode,
        lens=charter.research_lens,
        mock=mock,
        model=model,
        run_type=run_type,
    )

    _write_logged_json_artifact(run_dir / "metadata.json", metadata, run_logger)
    _write_logged_json_artifact(run_dir / "charter.json", charter, run_logger)
    _write_logged_json_artifact(run_dir / "research_plan.json", plan, run_logger)
    _write_logged_json_artifact(run_dir / "sources.json", sources, run_logger)
    _write_logged_json_artifact(run_dir / "source_map.json", source_map, run_logger)
    if source_content is not None:
        _write_logged_json_artifact(run_dir / "source_content.json", source_content, run_logger)
    if source_fetch_log is not None:
        _write_logged_json_artifact(
            run_dir / "source_fetch_log.json",
            source_fetch_log,
            run_logger,
        )
    if user_feedback is not None:
        _write_logged_json_artifact(run_dir / "user_feedback.json", user_feedback, run_logger)
    if specialist_analyses:
        _write_logged_json_artifact(
            run_dir / "specialist_analyses.json",
            specialist_analyses,
            run_logger,
        )
    if evidence_ledger is not None:
        _write_logged_json_artifact(
            run_dir / "evidence_ledger.json",
            evidence_ledger,
            run_logger,
        )
    _write_evidence_review_artifact(run_dir, evidence_ledger, status=status)
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
        _write_logged_json_artifact(run_dir / "qa_review.json", qa_review, run_logger)
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
        user_feedback=user_feedback,
        specialist_analyses=specialist_analyses or [],
        evidence_ledger=evidence_ledger,
        report=report,
        draft_report_path=draft_report_path,
        report_path=report_path,
        qa_review=qa_review,
    )


def _source_scores_by_id(source_map: SourceMap) -> dict[str, Any]:
    return {score.source_id: score for score in source_map.scores}


def _is_blocking_evidence_warning(warning: str) -> bool:
    return not warning.startswith(_NON_BLOCKING_EVIDENCE_WARNING_PREFIXES)


def _has_blocking_evidence_warnings(evidence_ledger: EvidenceLedgerModel) -> bool:
    return any(
        _is_blocking_evidence_warning(warning)
        for warning in evidence_ledger.validation_warnings
    )


def _evidence_review_markdown(evidence_ledger: EvidenceLedgerModel) -> str:
    blocking_warnings = [
        warning
        for warning in evidence_ledger.validation_warnings
        if _is_blocking_evidence_warning(warning)
    ]
    warning_lines = "\n".join(f"- {warning}" for warning in blocking_warnings)
    return (
        "# Evidence Review Required\n\n"
        "Synthesis and QA were not run because evidence validation produced "
        "blocking warnings.\n\n"
        "## Blocking Warnings\n"
        f"{warning_lines or '- None'}\n"
    )


def _write_evidence_review_artifact(
    run_dir: Path,
    evidence_ledger: EvidenceLedgerModel | None,
    *,
    status: str,
) -> None:
    if (
        status != "evidence_needs_review"
        or evidence_ledger is None
        or not _has_blocking_evidence_warnings(evidence_ledger)
    ):
        return
    (run_dir / "evidence_review.md").write_text(
        _evidence_review_markdown(evidence_ledger),
        encoding="utf-8",
    )


def _approved_sources(source_map: SourceMap) -> list[SourceCandidate]:
    score_lookup = _source_scores_by_id(source_map)
    included = [
        source
        for source in source_map.sources
        if score_lookup.get(source.id) is not None and score_lookup[source.id].include
    ]
    if included:
        return included
    ordered_ids = [score.source_id for score in source_map.scores[:5]]
    source_lookup = {source.id: source for source in source_map.sources}
    return [source_lookup[source_id] for source_id in ordered_ids if source_id in source_lookup]


def _claim_id_part(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    return normalized or "claim"


def _next_specialist_claim_id(
    *,
    specialist: str,
    original_id: str,
    used_ids: set[str],
) -> str:
    prefix = _claim_id_part(specialist).lower()
    claim_part = _claim_id_part(original_id)
    candidate = f"specialist_{prefix}_{claim_part}"
    suffix = 2
    while candidate in used_ids:
        candidate = f"specialist_{prefix}_{claim_part}_{suffix}"
        suffix += 1
    return candidate


def _deduplicate_claims(
    base_claims: list[EvidenceClaim],
    specialist_analyses: list[SpecialistAnalysis] | None = None,
) -> tuple[list[EvidenceClaim], list[str]]:
    deduped_claims: list[EvidenceClaim] = []
    warnings: list[str] = []
    used_ids: set[str] = set()
    first_content_by_id: dict[str, tuple[str, ...]] = {}

    claims_with_origin: list[tuple[EvidenceClaim, str | None]] = [
        (claim, None) for claim in base_claims
    ]
    for analysis in specialist_analyses or []:
        claims_with_origin.extend(
            (claim, analysis.specialist) for claim in analysis.evidence_claims
        )

    for claim, specialist in claims_with_origin:
        content_key = evidence_claim_content_key(claim)
        first_content_key = first_content_by_id.get(claim.id)
        if first_content_key is None:
            near_duplicate_of = next(
                (
                    existing_claim
                    for existing_claim in deduped_claims
                    if is_near_duplicate_claim(existing_claim, claim)
                ),
                None,
            )
            if near_duplicate_of is not None:
                warnings.append(
                    "Deduplicated near-duplicate evidence claim ID "
                    f"{claim.id}: preserved {near_duplicate_of.id} and dropped "
                    "a later claim with materially equivalent normalized text."
                )
                continue
            deduped_claims.append(claim)
            used_ids.add(claim.id)
            first_content_by_id[claim.id] = content_key
            continue

        if content_key == first_content_key:
            warnings.append(
                f"Deduplicated duplicate evidence claim ID {claim.id}: preserved "
                "the first occurrence and dropped a later identical claim."
            )
            continue

        if specialist is not None:
            near_duplicate_of = next(
                (
                    existing_claim
                    for existing_claim in deduped_claims
                    if is_near_duplicate_claim(existing_claim, claim)
                ),
                None,
            )
            if near_duplicate_of is not None:
                warnings.append(
                    "Deduplicated near-duplicate evidence claim ID "
                    f"{claim.id}: preserved {near_duplicate_of.id} and dropped "
                    "a later claim with materially equivalent normalized text."
                )
                continue
            new_id = _next_specialist_claim_id(
                specialist=specialist,
                original_id=claim.id,
                used_ids=used_ids,
            )
            deduped_claims.append(claim.model_copy(update={"id": new_id}))
            used_ids.add(new_id)
            first_content_by_id[new_id] = content_key
            warnings.append(
                f"Renamed conflicting specialist evidence claim ID {claim.id} "
                f"to {new_id}: claim/source content differed from the first "
                "occurrence."
            )
            continue

        warnings.append(
            f"Conflicting duplicate evidence claim ID {claim.id}: claim/source "
            "content differs from the first occurrence; preserved the first "
            "occurrence and blocked synthesis until unique IDs are supplied."
        )

    return deduped_claims, warnings


def _sanitize_evidence_claims_for_synthesis(
    claims: list[EvidenceClaim],
    *,
    source_map: SourceMap,
    high_confidence_authority_floor: float = 4,
) -> tuple[list[EvidenceClaim], list[str]]:
    source_lookup = {source.id: source for source in source_map.sources}
    score_lookup = _source_scores_by_id(source_map)
    sanitized_claims: list[EvidenceClaim] = []
    warnings: list[str] = []

    for claim in claims:
        source = source_lookup.get(claim.source_id) if claim.source_id else None
        has_claim_source_url = bool((claim.source_url or "").strip())
        has_source_map_url = source is not None and bool(source.url.strip())

        if not has_claim_source_url and not has_source_map_url:
            if not claim.source_id:
                warnings.append(
                    "Dropped unsupported evidence claim ID "
                    f"{claim.id} before synthesis: missing source id and source URL."
                )
                continue
            if source is not None:
                warnings.append(
                    "Dropped unsupported evidence claim ID "
                    f"{claim.id} before synthesis: source {claim.source_id} "
                    "has no usable URL."
                )
                continue

        quality_category = classify_evidence_claim(claim)
        if quality_category in {
            "source_metadata_only",
            "source_finding_aid",
            "unsupported_or_unclear",
        }:
            warnings.append(
                "Dropped unsupported evidence claim ID "
                f"{claim.id} before synthesis: evidence quality category "
                f"{quality_category}."
            )
            continue

        score = score_lookup.get(claim.source_id) if claim.source_id else None
        if (
            claim.confidence == "high"
            and score is not None
            and score.authority_score < high_confidence_authority_floor
        ):
            sanitized_claims.append(claim.model_copy(update={"confidence": "medium"}))
            warnings.append(
                "Downgraded evidence claim ID "
                f"{claim.id} from high to medium confidence before synthesis: "
                f"source {score.source_id} authority is {score.authority_score}."
            )
            continue

        sanitized_claims.append(claim)

    return sanitized_claims, warnings


def _extract_mock_evidence(
    *,
    charter: ResearchCharter,
    plan: ResearchPlan,
    source_map: SourceMap,
) -> EvidenceLedgerModel:
    claims: list[EvidenceClaim] = []
    score_lookup = _source_scores_by_id(source_map)
    for index, source in enumerate(_approved_sources(source_map), start=1):
        score = score_lookup.get(source.id)
        confidence: Confidence = (
            "high" if score is not None and score.authority_score >= 4 else "medium"
        )
        recommended_uses = ", ".join(source.recommended_uses[:2]) or source.source_type
        claims.append(
            EvidenceClaim(
                id=f"claim_{index}",
                claim=(
                    f"{charter.target} checkpoint coverage includes "
                    f"{recommended_uses} from {source.source_type.replace('_', ' ')} material."
                ),
                claim_type="fact",
                source_id=source.id,
                source_title=source.title,
                source_url=source.url,
                source_type=source.source_type,
                confidence=confidence,
                report_section=plan.report_sections[0] if plan.report_sections else "overview",
                quote_or_excerpt=source.relevance_rationale,
            )
        )
    ledger = EvidenceLedger(EvidenceExtractionResult(claims=claims).claims)
    ledger.validate(source_scores=score_lookup, source_map=source_map)
    return ledger.to_model()


def _validate_evidence(
    claims: list[EvidenceClaim],
    *,
    source_map: SourceMap,
) -> EvidenceLedgerModel:
    deduped_claims, dedupe_warnings = _deduplicate_claims(claims)
    sanitized_claims, sanitization_warnings = _sanitize_evidence_claims_for_synthesis(
        deduped_claims,
        source_map=source_map,
    )
    ledger = EvidenceLedger(sanitized_claims)
    ledger.validate(source_scores=_source_scores_by_id(source_map), source_map=source_map)
    ledger.validation_warnings = [
        *dedupe_warnings,
        *sanitization_warnings,
        *ledger.validation_warnings,
    ]
    return ledger.to_model()


def _validate_specialist_analysis_sources(
    analysis: SpecialistAnalysis,
    *,
    source_map: SourceMap,
) -> None:
    allowed_source_ids = {source.id for source in source_map.sources}
    referenced_source_ids = set(analysis.source_ids)
    unknown = sorted(
        source_id for source_id in referenced_source_ids if source_id not in allowed_source_ids
    )
    if unknown:
        raise ValueError(
            f"Specialist analysis {analysis.specialist} contains unknown source references: "
            f"{', '.join(unknown)}"
        )


def _run_specialist_analyses(
    *,
    agents: Any,
    charter: ResearchCharter,
    plan: ResearchPlan,
    source_map: SourceMap,
    evidence_ledger: EvidenceLedgerModel,
    selected_specialists: list[str],
    agent_runner: AgentRunner | None,
    user_feedback: UserFeedback | None = None,
    run_logger: RunLogger | None = None,
) -> list[SpecialistAnalysis]:
    analyses: list[SpecialistAnalysis] = []
    for specialist_key in runnable_specialist_agent_keys(selected_specialists):
        agent = getattr(agents, specialist_key)
        payload = {
            "specialist": specialist_key,
            "selected_specialists": selected_specialists,
            "charter": charter.model_dump(mode="json"),
            "research_plan": plan.model_dump(mode="json"),
            "source_map": source_map.model_dump(mode="json"),
            "evidence_ledger": evidence_ledger.model_dump(mode="json"),
            "instructions": [
                "Return a SpecialistAnalysis object only.",
                "Use the evidence_ledger as the factual base for specialist analysis.",
                "Use only source_map source IDs for source_ids and evidence claims.",
                "Do not bypass the evidence ledger with unsupported specialist facts.",
                "Every material specialist fact should become an evidence_claim.",
            ],
            "output_schema": "SpecialistAnalysis",
        }
        if user_feedback is not None:
            payload["user_feedback"] = _user_feedback_prompt_payload(user_feedback)
        analysis = cast(
            SpecialistAnalysis,
            _run_live_agent(
                specialist_key,
                agent,
                _json_prompt(f"Run {specialist_key} specialist analysis.", payload),
                agent_runner=agent_runner,
                run_logger=run_logger,
            ),
        )
        _validate_specialist_analysis_sources(analysis, source_map=source_map)
        analyses.append(analysis)
    return analyses


def _merge_specialist_claims(
    evidence_ledger: EvidenceLedgerModel,
    specialist_analyses: list[SpecialistAnalysis],
    *,
    source_map: SourceMap,
) -> EvidenceLedgerModel:
    if not any(analysis.evidence_claims for analysis in specialist_analyses):
        return evidence_ledger
    deduped_claims, dedupe_warnings = _deduplicate_claims(
        evidence_ledger.claims,
        specialist_analyses,
    )
    sanitized_claims, sanitization_warnings = _sanitize_evidence_claims_for_synthesis(
        deduped_claims,
        source_map=source_map,
    )
    existing_warnings = list(evidence_ledger.validation_warnings)
    ledger = EvidenceLedger(sanitized_claims)
    ledger.validate(source_scores=_source_scores_by_id(source_map), source_map=source_map)
    ledger.validation_warnings = [
        *existing_warnings,
        *dedupe_warnings,
        *sanitization_warnings,
        *ledger.validation_warnings,
    ]
    return ledger.to_model()


def _unique_nonempty(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_items: list[str] = []
    for item in items:
        normalized = item.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_items.append(normalized)
    return unique_items


def _format_markdown_bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _source_id_count(evidence_ledger: EvidenceLedgerModel) -> int:
    return len(
        {
            claim.source_id
            for claim in evidence_ledger.claims
            if claim.source_id is not None and claim.source_id.strip()
        }
    )


def _allowed_claim_ids(evidence_ledger: EvidenceLedgerModel) -> list[str]:
    return [claim.id for claim in evidence_ledger.claims]


def _specialist_analyses_payload_for_synthesis(
    specialist_analyses: list[SpecialistAnalysis],
    *,
    evidence_ledger: EvidenceLedgerModel,
) -> list[dict[str, Any]]:
    allowed_claim_ids = set(_allowed_claim_ids(evidence_ledger))
    payload: list[dict[str, Any]] = []
    for analysis in specialist_analyses:
        payload.append(
            analysis.model_copy(
                update={
                    "evidence_claims": [
                        claim
                        for claim in analysis.evidence_claims
                        if claim.id in allowed_claim_ids
                    ]
                }
            ).model_dump(mode="json")
        )
    return payload


def _claim_reference_rules(evidence_ledger: EvidenceLedgerModel) -> list[str]:
    allowed_count = len(evidence_ledger.claims)
    return [
        "Every material factual report statement must cite a claim ID from "
        "allowed_claim_ids in [claim_id] form.",
        "Use only allowed_claim_ids; do not invent, reuse, or restore dropped "
        "claim IDs.",
        "allowed_claim_ids are exact, case-sensitive strings. If a numeric "
        "sequence skips an ID, the skipped ID is not allowed.",
        "Do not cite claim IDs from specialist_analyses unless that exact ID "
        "is present in allowed_claim_ids.",
        "specialist_analyses in this payload are filtered for synthesis; the "
        "final evidence_ledger and allowed_claim_ids are authoritative.",
        "If a point would require a missing claim ID, omit it or rephrase it "
        "as an open question or evidence gap.",
        "Populate claim_ids with every allowed claim ID cited in markdown.",
        "Before returning, compare every bracketed claim ID in markdown and "
        "every item in claim_ids against allowed_claim_ids; remove or rewrite "
        "anything that does not match exactly.",
        f"The final evidence ledger currently contains {allowed_count} allowed claim IDs.",
    ]


def _synthesis_quality_rules() -> list[str]:
    return [
        "Use source_content-derived evidence claims as the basis for report claims.",
        "Do not promote CNBC/news summaries, transcript summaries, or source-finding "
        "aids into Costco-specific strategy unless a concrete evidence claim directly "
        "supports the strategy statement.",
        "Recent developments must cite direct evidence claims from fetched source "
        "content. If latest earnings release or transcript support is missing, say "
        "that it was not verified from available sources.",
        "Supplier-meeting recommendations require direct claim IDs or an explicit "
        "caveat that the point is a hypothesis or question to confirm with Costco.",
        "Separate directly supported facts, cautious inferences, and unknowns/open "
        "questions in the draft.",
        "Quartr pages, source-finding aids, search-result pages, and source-map "
        "rationales are not strategic evidence.",
    ]


def _synthesis_source_evidence_context(
    *,
    source_map: SourceMap,
    source_content: list[SourceContent],
    source_fetch_log: SourceFetchLog | None,
) -> dict[str, Any]:
    source_lookup = {source.id: source for source in source_map.sources}
    fetched_source_ids = [content.source_id for content in source_content]
    fetched_source_id_set = set(fetched_source_ids)
    direct_source_types = {"corporate_filing", "investor_material", "primary_company"}
    fetched_direct_source_ids = [
        source_id
        for source_id in fetched_source_ids
        if source_lookup.get(source_id) is not None
        and source_lookup[source_id].source_type in direct_source_types
    ]
    candidate_direct_source_ids = [
        source.id for source in source_map.sources if source.source_type in direct_source_types
    ]
    failed_or_skipped_source_ids: list[str] = []
    if source_fetch_log is not None:
        failed_or_skipped_source_ids = [
            result.source_id
            for result in source_fetch_log.results
            if result.status in {"failed", "skipped"}
        ]

    warnings: list[str] = []
    if candidate_direct_source_ids and not fetched_direct_source_ids:
        warnings.append(
            "Primary/company/investor source candidates were discovered but no readable "
            "direct source content was fetched. Treat Costco recent developments and "
            "strategy as unverified unless directly supported by fetched evidence."
        )
    if fetched_source_ids and not fetched_direct_source_ids:
        warnings.append(
            "Fetched source content is secondary or indirect only. State this source "
            "gap and avoid presenting Costco current strategy as verified."
        )
    if not fetched_source_ids:
        warnings.append(
            "No fetched source content is available. Use only evidence gaps and open "
            "questions for current or recent-development points."
        )

    return {
        "fetched_source_ids": fetched_source_ids,
        "fetched_direct_source_ids": fetched_direct_source_ids,
        "candidate_direct_source_ids": candidate_direct_source_ids,
        "failed_or_skipped_source_ids": failed_or_skipped_source_ids,
        "secondary_or_indirect_only": bool(fetched_source_id_set and not fetched_direct_source_ids),
        "warnings": warnings,
    }


def _report_revision_markdown(
    *,
    error: ReportSectionValidationError,
    evidence_ledger: EvidenceLedgerModel,
) -> str:
    allowed_claim_lines = "\n".join(
        f"- {claim_id}" for claim_id in _allowed_claim_ids(evidence_ledger)
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


def _write_report_revision_artifact(
    run_dir: Path,
    *,
    error: ReportSectionValidationError,
    evidence_ledger: EvidenceLedgerModel,
    run_logger: RunLogger | None = None,
) -> None:
    _write_logged_text_artifact(
        run_dir / "report_revision.md",
        _report_revision_markdown(error=error, evidence_ledger=evidence_ledger),
        run_logger,
    )


def _section_fill_lines(
    section: str,
    *,
    plan: ResearchPlan,
    source_map: SourceMap,
    evidence_ledger: EvidenceLedgerModel,
) -> list[str]:
    open_questions = _unique_nonempty(
        [
            *plan.checkpoint_questions,
            *source_map.gaps,
            *plan.data_gaps,
        ]
    )
    evidence_lines = [
        f"{claim.claim} [{claim.id}]" for claim in evidence_ledger.claims[:5]
    ]
    risk_lines = _unique_nonempty([*plan.known_risks, *source_map.gaps])

    if section == "What We Know":
        return evidence_lines or [
            "No directly supported facts were available in the evidence ledger."
        ]
    if section in {"What We Do Not Know", "Open Questions"}:
        return open_questions or [
            "No open questions were identified from checkpoint questions, "
            "source-map gaps, or plan data gaps."
        ]
    if section == "Questions to Ask":
        return plan.checkpoint_questions or [
            "Ask which unanswered research gaps matter most for the meeting."
        ]
    if section in {"Risks", "Risks and Watchouts"}:
        return risk_lines or [
            "Risk assessment is limited by the available evidence set."
        ]
    if section == "Evidence Limitations":
        claim_count = len(evidence_ledger.claims)
        source_count = _source_id_count(evidence_ledger)
        return [
            (
                f"Evidence is thin: {claim_count} evidence claims across "
                f"{source_count} source IDs."
            ),
            "Treat unsupported conclusions as open questions until more sources are added.",
        ]
    if section == "Source Appendix":
        return []
    if section in {"Business Overview", "Industry Definition"}:
        return evidence_lines or [
            "No evidence-backed overview was available for this section."
        ]
    if section in {
        "Context for Meeting",
        "Supplier/Buyer Angle",
        "Market Context",
        "Competitive Landscape",
        "Recent Developments",
        "Value Chain",
        "Key Players",
        "Demand Drivers",
    }:
        return [
            "No direct evidence-backed content was available for this section; "
            "treat it as an open question."
        ]
    return [
        "No evidence-backed content was available for this required section."
    ]


def _source_content_payload(
    source_content: list[SourceContent],
    *,
    max_total_chars: int = 16000,
    max_chunks_per_source: int = 5,
    max_chunk_chars: int = 1200,
) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    remaining_chars = max_total_chars
    for content in source_content:
        if remaining_chars <= 0:
            break
        chunks: list[dict[str, Any]] = []
        for chunk in _select_source_chunks(
            content.chunks,
            max_chunks=max_chunks_per_source,
        ):
            if remaining_chars <= 0:
                break
            text = chunk.text[: min(max_chunk_chars, remaining_chars)]
            remaining_chars -= len(text)
            chunks.append(
                {
                    "source_id": chunk.source_id,
                    "url": chunk.url,
                    "chunk_id": chunk.chunk_id,
                    "index": chunk.index,
                    "text": text,
                }
            )
        payload.append(
            {
                "source_id": content.source_id,
                "url": content.url,
                "content_type": content.content_type,
                "title": content.title,
                "excerpt": content.excerpt,
                "chunks": chunks,
            }
        )
    return payload


def _select_source_chunks(
    chunks: list[SourceChunk],
    *,
    max_chunks: int,
) -> list[SourceChunk]:
    if len(chunks) <= max_chunks:
        return list(chunks)
    ranked = sorted(
        enumerate(chunks),
        key=lambda item: (_source_chunk_signal_score(item[1].text), -item[0]),
        reverse=True,
    )
    selected_indexes = sorted(index for index, _chunk in ranked[:max_chunks])
    return [chunks[index] for index in selected_indexes]


def _source_chunk_signal_score(text: str) -> float:
    lowered = text.lower()
    alpha_count = sum(character.isalpha() for character in text)
    digit_count = sum(character.isdigit() for character in text)
    char_count = max(len(text), 1)
    word_count = len(re.findall(r"[a-zA-Z]{4,}", text))
    score = word_count * (alpha_count / char_count)

    for marker in (
        "business",
        "earnings",
        "member",
        "membership",
        "merchandise",
        "net sales",
        "risk",
        "sales",
        "supplier",
        "warehouse",
    ):
        if marker in lowered:
            score += 25

    score -= 40 * lowered.count("us-gaap")
    score -= 40 * lowered.count("fasb.org")
    score -= 10 * lowered.count("0000909832")
    score -= 20 * (digit_count / char_count)
    return score


def _source_fetch_log_payload(source_fetch_log: SourceFetchLog | None) -> dict[str, Any] | None:
    if source_fetch_log is None:
        return None
    return {
        "results": [
            {
                "source_id": result.source_id,
                "url": result.url,
                "status": result.status,
                "content_type": result.content_type,
                "title": result.title,
                "excerpt": result.excerpt,
                "error": result.error,
                "text_char_count": result.text_char_count,
                "chunk_count": result.chunk_count,
                "fetched_url": result.fetched_url,
            }
            for result in source_fetch_log.results
        ]
    }


def _repair_missing_report_sections(
    report: Report,
    *,
    plan: ResearchPlan,
    source_map: SourceMap,
    evidence_ledger: EvidenceLedgerModel,
    template_name: str | None,
) -> Report:
    missing = missing_report_sections(
        report,
        template_name=template_name,
        evidence_ledger=evidence_ledger,
        source_map=source_map,
    )
    if not missing:
        return report

    sections: list[str] = []
    for section in missing:
        if section == "Source Appendix":
            source_appendix = render_source_appendix(source_map)
            if source_appendix.startswith("# "):
                source_appendix = f"#{source_appendix}"
            sections.append(source_appendix.rstrip())
            continue
        lines = _section_fill_lines(
            section,
            plan=plan,
            source_map=source_map,
            evidence_ledger=evidence_ledger,
        )
        sections.append(f"## {section}\n{_format_markdown_bullets(lines)}")

    markdown = f"{report.markdown.rstrip()}\n\n" + "\n\n".join(sections) + "\n"
    return report.model_copy(update={"markdown": markdown})


def _should_write_final_report(
    *,
    report: Report | None,
    qa_requested: bool,
    qa_review: QAReview | None,
) -> bool:
    return (
        report is not None
        and qa_requested
        and qa_review is not None
        and not has_high_severity_issues(qa_review)
    )


def _create_mock_report(
    *,
    charter: ResearchCharter,
    plan: ResearchPlan,
    source_map: SourceMap,
    evidence_ledger: EvidenceLedgerModel,
) -> Report:
    ledger = EvidenceLedger(evidence_ledger.claims)
    ledger.validation_warnings = list(evidence_ledger.validation_warnings)
    raise_if_report_has_unsupported_claims(ledger)
    report = render_mock_report(
        charter=charter,
        plan=plan,
        source_map=source_map,
        evidence_ledger=evidence_ledger,
    )
    template_name = select_report_template_name(charter)
    report = _repair_missing_report_sections(
        report,
        plan=plan,
        source_map=source_map,
        evidence_ledger=evidence_ledger,
        template_name=template_name,
    )
    validate_report_traceability(report, evidence_ledger=evidence_ledger, source_map=source_map)
    validate_report_sections(
        report,
        template_name=template_name,
        evidence_ledger=evidence_ledger,
        source_map=source_map,
    )
    return report


def _run_qa_review(
    *,
    agents: Any,
    charter: ResearchCharter,
    source_map: SourceMap,
    evidence_ledger: EvidenceLedgerModel,
    report: Report,
    agent_runner: AgentRunner | None,
    run_logger: RunLogger | None = None,
) -> QAReview:
    template_name = select_report_template_name(charter)
    deterministic_review = run_deterministic_qa_checks(
        source_map=source_map,
        evidence_ledger=evidence_ledger,
        draft_report=report,
        template_name=template_name,
    )
    qa_payload = {
        "research_charter": charter.model_dump(mode="json"),
        "source_map": source_map.model_dump(mode="json"),
        "evidence_ledger": evidence_ledger.model_dump(mode="json"),
        "draft_report": report.model_dump(mode="json"),
        "instructions": [
            "Review the draft report for reliability, source quality, and usefulness.",
            "Do not rewrite the report.",
            "High-severity issues should block final publication.",
            "Do not treat Quartr pages, source-finding aids, or source-map rationales "
            "as strategic evidence.",
            "Block recent-development claims that lack concrete source-content support.",
            "Flag supplier-meeting recommendations that lack direct claim IDs or "
            "explicit caveats.",
        ],
        "output_schema": "QAReview",
    }
    agent_review = cast(
        QAReview,
        _run_live_agent(
            "qa",
            agents.qa,
            _json_prompt("Run QA and red-team review on this draft report.", qa_payload),
            agent_runner=agent_runner,
            run_logger=run_logger,
        ),
    )
    return merge_qa_reviews(deterministic_review, agent_review)


def _continue_research_impl(
    run_id_or_path: str | Path,
    *,
    qa: bool = False,
    mock: bool | None = None,
    runs_dir: str | Path | None = None,
    agent_runner: AgentRunner | None = None,
    model: str | None = None,
    search_client: WebSearchClient | None = None,
    source_fetcher: SourceFetcher | None = None,
    started_at: datetime,
    run_logger: RunLogger,
) -> ResearchRunResult:
    """Continue an existing checkpoint run using saved user feedback."""
    run_dir = _resolve_run_dir(run_id_or_path, runs_dir)
    if not run_dir.exists() or not run_dir.is_dir():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    metadata = cast(RunMetadata, _read_model_artifact(run_dir / "metadata.json", RunMetadata))
    charter = cast(
        ResearchCharter,
        _read_model_artifact(run_dir / "charter.json", ResearchCharter),
    )
    plan = cast(
        ResearchPlan,
        _read_model_artifact(run_dir / "research_plan.json", ResearchPlan),
    )
    source_map = cast(SourceMap, _read_model_artifact(run_dir / "source_map.json", SourceMap))
    feedback = load_user_feedback(run_dir)

    charter = _charter_with_feedback(charter, feedback)
    source_map = _source_map_with_feedback(source_map, feedback)
    sources = list(source_map.sources)
    effective_mock = metadata.mock if mock is None else mock

    if effective_mock:
        selected_specialists = select_specialists(charter, plan)
        mock_specialist_analyses = build_mock_specialist_analyses(
            runnable_specialist_agent_keys(selected_specialists),
            source_map,
        )
        evidence_ledger = _extract_mock_evidence(
            charter=charter,
            plan=plan,
            source_map=source_map,
        )
        evidence_ledger = _merge_specialist_claims(
            evidence_ledger,
            mock_specialist_analyses,
            source_map=source_map,
        )
        report = (
            _create_mock_report(
                charter=charter,
                plan=plan,
                source_map=source_map,
                evidence_ledger=evidence_ledger,
            )
            if not _has_blocking_evidence_warnings(evidence_ledger)
            else None
        )
        qa_review = (
            run_deterministic_qa_checks(
                source_map=source_map,
                evidence_ledger=evidence_ledger,
                draft_report=report,
                template_name=select_report_template_name(charter),
            )
            if qa and report is not None
            else None
        )
        has_blocking_qa = qa_review is not None and has_high_severity_issues(qa_review)
        write_final_report = _should_write_final_report(
            report=report,
            qa_requested=qa,
            qa_review=qa_review,
        )
        return _write_checkpoint_artifacts(
            run_id=metadata.run_id,
            run_dir=run_dir,
            request=metadata.request,
            mode=charter.depth,
            mock=effective_mock,
            charter=charter,
            plan=plan,
            sources=sources,
            source_map=source_map,
            user_feedback=feedback,
            specialist_analyses=mock_specialist_analyses,
            evidence_ledger=evidence_ledger,
            report=report,
            qa_review=qa_review,
            write_final_report=write_final_report,
            status=(
                "needs_review"
                if has_blocking_qa
                else "report_ready"
                if report is not None and qa
                else "draft_needs_qa"
                if report is not None
                else "evidence_needs_review"
            ),
            started_at=started_at,
            model=model or metadata.model,
            run_type="continue",
            run_logger=run_logger,
        )

    search_client = search_client or WebSearchClient()
    agents = create_agent_set(model=model, search_client=search_client)
    selected_specialists = select_specialists(charter, plan)
    approved_sources = _approved_sources(source_map)
    run_logger.tool_call("source_ingestion", status="start", source_count=len(source_map.sources))
    source_content, source_fetch_log = ingest_source_content(
        source_map,
        fetcher=source_fetcher,
    )
    run_logger.tool_call(
        "source_ingestion",
        status="end",
        fetched_count=len(source_content),
    )
    feedback_payload = _user_feedback_prompt_payload(feedback)
    evidence_payload = {
        "charter": charter.model_dump(mode="json"),
        "research_plan": plan.model_dump(mode="json"),
        "source_map": source_map.model_dump(mode="json"),
        "approved_sources": [source.model_dump(mode="json") for source in approved_sources],
        "source_content": _source_content_payload(source_content),
        "source_fetch_log": _source_fetch_log_payload(source_fetch_log),
        "source_scores": [
            score.model_dump(mode="json")
            for score in source_map.scores
            if any(source.id == score.source_id for source in approved_sources)
        ],
        "user_feedback": feedback_payload,
        "instructions": [
            "Continue this existing checkpoint run without rediscovering sources.",
            "Extract evidence claims only from approved_sources.",
            "Treat user_feedback as steering context, not as factual evidence.",
            "Prefer source_content chunks over search snippets and source metadata.",
            "The source_content payload is chunk-limited for model context; "
            "use only the provided chunks for quote_or_excerpt.",
            "When source_content is available, quote_or_excerpt must be a short "
            "verbatim substring copied from the fetched source text, not a paraphrase.",
            "If a source fetch failed or was skipped, keep confidence conservative "
            "and do not treat source metadata as evidence.",
            "Every fact claim must include source_id or source_url.",
            "Use high confidence only for authority score >= 4 sources.",
            "Do not write a report.",
        ],
        "output_schema": "EvidenceExtractionResult",
    }
    run_logger.stage_start("evidence_extraction")
    evidence_result = cast(
        EvidenceExtractionResult,
        _run_live_agent(
            "evidence_extraction",
            agents.evidence_extraction,
            _json_prompt("Extract evidence claims from approved sources.", evidence_payload),
            agent_runner=agent_runner,
            run_logger=run_logger,
        ),
    )
    run_logger.stage_end("evidence_extraction")
    evidence_ledger = _validate_evidence(evidence_result.claims, source_map=source_map)
    specialist_analyses: list[SpecialistAnalysis] = []
    if not _has_blocking_evidence_warnings(evidence_ledger):
        run_logger.stage_start("specialists")
        specialist_analyses = _run_specialist_analyses(
            agents=agents,
            charter=charter,
            plan=plan,
            source_map=source_map,
            evidence_ledger=evidence_ledger,
            selected_specialists=selected_specialists,
            agent_runner=agent_runner,
            user_feedback=feedback,
            run_logger=run_logger,
        )
        run_logger.stage_end("specialists")
    evidence_ledger = _merge_specialist_claims(
        evidence_ledger,
        specialist_analyses,
        source_map=source_map,
    )

    report = None
    qa_review = None
    status = (
        "evidence_needs_review"
        if _has_blocking_evidence_warnings(evidence_ledger)
        else "evidence_ready"
    )
    if not _has_blocking_evidence_warnings(evidence_ledger):
        template_name = select_report_template_name(charter)
        required_sections = required_sections_for_report(
            template_name=template_name,
            evidence_ledger=evidence_ledger,
            source_map=source_map,
        )
        synthesis_payload = {
            "charter": charter.model_dump(mode="json"),
            "research_plan": plan.model_dump(mode="json"),
            "source_map": source_map.model_dump(mode="json"),
            "evidence_ledger": evidence_ledger.model_dump(mode="json"),
            "allowed_claim_ids": _allowed_claim_ids(evidence_ledger),
            "specialist_analyses": _specialist_analyses_payload_for_synthesis(
                specialist_analyses,
                evidence_ledger=evidence_ledger,
            ),
            "user_feedback": feedback_payload,
            "selected_report_template": {
                "name": template_name,
                "markdown": load_template(template_name),
            },
            "required_sections": required_sections,
            "section_requirements": [
                "Follow required_sections exactly; do not rename or merge them.",
                "Use the selected_report_template heading sequence as the report outline.",
                "For meeting prep, What We Do Not Know is mandatory.",
                "If Evidence Limitations is listed, explain that the source set is thin.",
                "Reflect user_feedback priorities in open questions and caveats.",
                "Treat user_feedback as user context, not as source evidence.",
                "If needed, write empty-but-honest gap sections from "
                "research_plan.checkpoint_questions, source_map.gaps, "
                "research_plan.data_gaps, or user_feedback.",
                "Do not invent factual content to fill required sections.",
            ],
            "source_reference_rule": (
                "Use only source IDs from source_map. Include Source IDs and URLs "
                "in the Source Appendix."
            ),
            "claim_reference_rules": _claim_reference_rules(evidence_ledger),
            "claim_reference_rule": (
                "Use only IDs in allowed_claim_ids. Every material factual report "
                "statement must cite an allowed evidence ledger claim ID in "
                "[claim_id] form. Populate claim_ids with every allowed claim ID "
                "cited in markdown."
            ),
            "quality_rules": _synthesis_quality_rules(),
            "source_evidence_context": _synthesis_source_evidence_context(
                source_map=source_map,
                source_content=source_content,
                source_fetch_log=source_fetch_log,
            ),
            "output_schema": "Report",
        }
        run_logger.stage_start("synthesis")
        report = cast(
            Report,
            _run_live_agent(
                "synthesis",
                agents.synthesis,
                _json_prompt("Generate a cited markdown report.", synthesis_payload),
                agent_runner=agent_runner,
                run_logger=run_logger,
            ),
        )
        run_logger.stage_end("synthesis")
        report = _repair_missing_report_sections(
            report,
            plan=plan,
            source_map=source_map,
            evidence_ledger=evidence_ledger,
            template_name=template_name,
        )
        try:
            validate_report_traceability(
                report,
                evidence_ledger=evidence_ledger,
                source_map=source_map,
            )
            validate_report_sections(
                report,
                template_name=template_name,
                evidence_ledger=evidence_ledger,
                source_map=source_map,
            )
        except ReportSectionValidationError as exc:
            report = report.model_copy(update={"status": "draft_needs_revision"})
            _write_report_revision_artifact(
                run_dir,
                error=exc,
                evidence_ledger=evidence_ledger,
                run_logger=run_logger,
            )
            status = "draft_needs_revision"
        else:
            if qa:
                run_logger.stage_start("qa")
                qa_review = _run_qa_review(
                    agents=agents,
                    charter=charter,
                    source_map=source_map,
                    evidence_ledger=evidence_ledger,
                    report=report,
                    agent_runner=agent_runner,
                    run_logger=run_logger,
                )
                run_logger.stage_end("qa")
                status = "needs_review" if has_high_severity_issues(qa_review) else "report_ready"
            else:
                status = "draft_needs_qa"

    write_final_report = _should_write_final_report(
        report=report,
        qa_requested=qa,
        qa_review=qa_review,
    )
    return _write_checkpoint_artifacts(
        run_id=metadata.run_id,
        run_dir=run_dir,
        request=metadata.request,
        mode=charter.depth,
        mock=effective_mock,
        charter=charter,
        plan=plan,
        sources=sources,
        source_map=source_map,
        source_content=source_content,
        source_fetch_log=source_fetch_log,
        user_feedback=feedback,
        specialist_analyses=specialist_analyses,
        evidence_ledger=evidence_ledger,
        report=report,
        qa_review=qa_review,
        write_final_report=write_final_report,
        status=status,
        started_at=started_at,
        model=model or metadata.model,
        run_type="continue",
        run_logger=run_logger,
    )


def continue_research(
    run_id_or_path: str | Path,
    *,
    qa: bool = False,
    mock: bool | None = None,
    runs_dir: str | Path | None = None,
    agent_runner: AgentRunner | None = None,
    model: str | None = None,
    search_client: WebSearchClient | None = None,
    source_fetcher: SourceFetcher | None = None,
) -> ResearchRunResult:
    run_dir = _resolve_run_dir(run_id_or_path, runs_dir)
    if not run_dir.exists() or not run_dir.is_dir():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    started_at = datetime.now(timezone.utc)
    metadata: RunMetadata | None = None
    try:
        metadata = cast(RunMetadata, _read_model_artifact(run_dir / "metadata.json", RunMetadata))
        run_id = metadata.run_id
        request = metadata.request
        mode = metadata.mode
        lens = metadata.lens
        effective_mock = metadata.mock if mock is None else mock
    except Exception:
        run_id = run_dir.name
        request = ""
        mode = "standard"
        lens = "general"
        effective_mock = bool(mock)

    run_logger = RunLogger(run_dir, run_id)
    run_logger.stage_start("continue")
    try:
        result = _continue_research_impl(
            run_dir,
            qa=qa,
            mock=mock,
            runs_dir=runs_dir,
            agent_runner=agent_runner,
            model=model,
            search_client=search_client,
            source_fetcher=source_fetcher,
            started_at=started_at,
            run_logger=run_logger,
        )
    except Exception as exc:
        run_logger.error(exc, stage="continue")
        _write_failure_artifacts(
            run_id=run_id,
            run_dir=run_dir,
            request=request,
            mode=mode,
            lens=lens,
            mock=effective_mock,
            model=model or (metadata.model if metadata is not None else None),
            run_type="continue",
            started_at=started_at,
            error=exc,
            run_logger=run_logger,
        )
        raise
    run_logger.stage_end("continue", status=result.metadata.status)
    return result


def _run_research_impl(
    request: str,
    *,
    mode: str = "standard",
    lens: str | None = None,
    checkpoint_only: bool = False,
    full: bool = False,
    qa: bool = False,
    mock: bool = True,
    runs_dir: str | Path | None = None,
    agent_runner: AgentRunner | None = None,
    model: str | None = None,
    search_client: WebSearchClient | None = None,
    source_fetcher: SourceFetcher | None = None,
    run_id: str,
    run_dir: Path,
    started_at: datetime,
    run_type: RunType,
    run_logger: RunLogger,
) -> ResearchRunResult:
    """Run the checkpoint workflow and write local artifacts."""
    if qa and not full:
        raise NotImplementedError("Use --full with --qa.")
    if not checkpoint_only and not full:
        raise NotImplementedError("Use --checkpoint-only or --full.")

    if mock:
        charter = create_mock_charter(request, mode=mode, lens=lens)
        plan = create_mock_plan(charter)
        sources = discover_mock_sources(charter)
        source_map = build_source_map(
            sources,
            required_source_types=plan.required_source_types,
            mock=True,
        )
        selected_specialists = select_specialists(charter, plan)
        mock_specialist_analyses = (
            build_mock_specialist_analyses(
                runnable_specialist_agent_keys(selected_specialists),
                source_map,
            )
            if full
            else []
        )
        evidence_ledger = (
            _extract_mock_evidence(charter=charter, plan=plan, source_map=source_map)
            if full
            else None
        )
        if evidence_ledger is not None and mock_specialist_analyses:
            evidence_ledger = _merge_specialist_claims(
                evidence_ledger,
                mock_specialist_analyses,
                source_map=source_map,
            )
        report = (
            _create_mock_report(
                charter=charter,
                plan=plan,
                source_map=source_map,
                evidence_ledger=evidence_ledger,
            )
            if evidence_ledger is not None
            and not _has_blocking_evidence_warnings(evidence_ledger)
            else None
        )
        qa_review = (
            run_deterministic_qa_checks(
                source_map=source_map,
                evidence_ledger=evidence_ledger,
                draft_report=report,
                template_name=select_report_template_name(charter),
            )
            if qa and evidence_ledger is not None and report is not None
            else None
        )
        has_blocking_qa = qa_review is not None and has_high_severity_issues(qa_review)
        write_final_report = _should_write_final_report(
            report=report,
            qa_requested=qa,
            qa_review=qa_review,
        )
        return _write_checkpoint_artifacts(
            run_id=run_id,
            run_dir=run_dir,
            request=request,
            mode=mode,
            mock=mock,
            charter=charter,
            plan=plan,
            sources=sources,
            source_map=source_map,
            specialist_analyses=mock_specialist_analyses,
            evidence_ledger=evidence_ledger,
            report=report,
            qa_review=qa_review,
            write_final_report=write_final_report,
            status=(
                "needs_review"
                if has_blocking_qa
                else "report_ready"
                if report is not None and qa
                else "draft_needs_qa"
                if report is not None
                else "evidence_needs_review"
                if evidence_ledger is not None
                and _has_blocking_evidence_warnings(evidence_ledger)
                else "evidence_ready"
                if evidence_ledger is not None
                else "checkpoint_ready"
            ),
            started_at=started_at,
            model=model,
            run_type=run_type,
            run_logger=run_logger,
        )

    search_client = search_client or WebSearchClient()
    agents = create_agent_set(model=model, search_client=search_client)
    intake_payload = {
        "request": request,
        "mode": mode,
        "lens_override": lens,
        "output_schema": "ResearchCharter",
    }
    run_logger.stage_start("intake")
    charter = cast(
        ResearchCharter,
        _run_live_agent(
            "intake",
            agents.intake,
            _json_prompt("Create a research charter for this request.", intake_payload),
            agent_runner=agent_runner,
            run_logger=run_logger,
        ),
    )
    run_logger.stage_end("intake")

    planner_payload = {
        "charter": charter.model_dump(mode="json"),
        "output_schema": "ResearchPlan",
    }
    run_logger.stage_start("planner")
    plan = cast(
        ResearchPlan,
        _run_live_agent(
            "planner",
            agents.planner,
            _json_prompt("Create a checkpoint research plan from this charter.", planner_payload),
            agent_runner=agent_runner,
            run_logger=run_logger,
        ),
    )
    run_logger.stage_end("planner")

    source_search_queries = build_source_search_queries(charter, plan)
    run_logger.tool_call(
        "web_search",
        status="start",
        query_count=len(source_search_queries),
    )
    raw_search_results = search_client.search_many(source_search_queries)
    run_logger.tool_call(
        "web_search",
        status="end",
        result_count=len(raw_search_results),
    )
    source_discovery_payload = {
        "charter": charter.model_dump(mode="json"),
        "research_plan": plan.model_dump(mode="json"),
        "source_search_queries": source_search_queries,
        "raw_search_results": [
            result.model_dump(mode="json") for result in raw_search_results
        ],
        "instructions": [
            "Classify the raw_search_results into structured source candidates.",
            "Return candidate sources only; do not write the report.",
            "Do not invent URLs; omit unusable results instead.",
        ],
        "output_schema": "SourceDiscoveryResult",
    }
    run_logger.stage_start("source_discovery")
    source_discovery = cast(
        SourceDiscoveryResult,
        _run_live_agent(
            "source_discovery",
            agents.source_discovery,
            _json_prompt("Discover and classify checkpoint sources.", source_discovery_payload),
            agent_runner=agent_runner,
            run_logger=run_logger,
        ),
    )
    run_logger.stage_end("source_discovery")
    sources = list(source_discovery.sources)
    source_map = build_source_map(
        sources,
        required_source_types=plan.required_source_types,
        mock=False,
    )
    if source_discovery.gaps:
        source_map.gaps.extend(source_discovery.gaps)

    evidence_ledger = None
    report = None
    qa_review = None
    source_content: list[SourceContent] = []
    source_fetch_log: SourceFetchLog | None = None
    specialist_analyses: list[SpecialistAnalysis] = []
    status = "checkpoint_ready"
    if full:
        selected_specialists = select_specialists(charter, plan)
        approved_sources = _approved_sources(source_map)
        run_logger.tool_call("source_ingestion", status="start", source_count=len(source_map.sources))
        source_content, source_fetch_log = ingest_source_content(
            source_map,
            fetcher=source_fetcher,
        )
        run_logger.tool_call(
            "source_ingestion",
            status="end",
            fetched_count=len(source_content),
        )
        evidence_payload = {
            "charter": charter.model_dump(mode="json"),
            "research_plan": plan.model_dump(mode="json"),
            "source_map": source_map.model_dump(mode="json"),
            "approved_sources": [source.model_dump(mode="json") for source in approved_sources],
            "source_content": _source_content_payload(source_content),
            "source_fetch_log": _source_fetch_log_payload(source_fetch_log),
            "source_scores": [
                score.model_dump(mode="json")
                for score in source_map.scores
                if any(source.id == score.source_id for source in approved_sources)
            ],
            "instructions": [
                "Extract evidence claims only from approved_sources.",
                "Prefer source_content chunks over search snippets and source metadata.",
                "The source_content payload is chunk-limited for model context; "
                "use only the provided chunks for quote_or_excerpt.",
                "When source_content is available, quote_or_excerpt must be a short "
                "verbatim substring copied from the fetched source text, not a paraphrase.",
                "If a source fetch failed or was skipped, keep confidence conservative "
                "and do not treat source metadata as evidence.",
                "Every fact claim must include source_id or source_url.",
                "Use high confidence only for authority score >= 4 sources.",
                "Do not write a report.",
            ],
            "output_schema": "EvidenceExtractionResult",
        }
        run_logger.stage_start("evidence_extraction")
        evidence_result = cast(
            EvidenceExtractionResult,
            _run_live_agent(
                "evidence_extraction",
                agents.evidence_extraction,
                _json_prompt("Extract evidence claims from approved sources.", evidence_payload),
                agent_runner=agent_runner,
                run_logger=run_logger,
            ),
        )
        run_logger.stage_end("evidence_extraction")
        evidence_ledger = _validate_evidence(evidence_result.claims, source_map=source_map)
        status = (
            "evidence_needs_review"
            if _has_blocking_evidence_warnings(evidence_ledger)
            else "evidence_ready"
        )
        if not _has_blocking_evidence_warnings(evidence_ledger):
            run_logger.stage_start("specialists")
            specialist_analyses = _run_specialist_analyses(
                agents=agents,
                charter=charter,
                plan=plan,
                source_map=source_map,
                evidence_ledger=evidence_ledger,
                selected_specialists=selected_specialists,
                agent_runner=agent_runner,
                run_logger=run_logger,
            )
            run_logger.stage_end("specialists")
        evidence_ledger = _merge_specialist_claims(
            evidence_ledger,
            specialist_analyses,
            source_map=source_map,
        )
        status = (
            "evidence_needs_review"
            if _has_blocking_evidence_warnings(evidence_ledger)
            else "evidence_ready"
        )
        if not _has_blocking_evidence_warnings(evidence_ledger):
            template_name = select_report_template_name(charter)
            required_sections = required_sections_for_report(
                template_name=template_name,
                evidence_ledger=evidence_ledger,
                source_map=source_map,
            )
            synthesis_payload = {
                "charter": charter.model_dump(mode="json"),
                "research_plan": plan.model_dump(mode="json"),
                "source_map": source_map.model_dump(mode="json"),
                "evidence_ledger": evidence_ledger.model_dump(mode="json"),
                "allowed_claim_ids": _allowed_claim_ids(evidence_ledger),
                "specialist_analyses": _specialist_analyses_payload_for_synthesis(
                    specialist_analyses,
                    evidence_ledger=evidence_ledger,
                ),
                "selected_report_template": {
                    "name": template_name,
                    "markdown": load_template(template_name),
                },
                "required_sections": required_sections,
                "section_requirements": [
                    "Follow required_sections exactly; do not rename or merge them.",
                    "Use the selected_report_template heading sequence as the report outline.",
                    "For meeting prep, What We Do Not Know is mandatory.",
                    "If Evidence Limitations is listed, explain that the source set is thin.",
                    "If needed, write empty-but-honest gap sections from "
                    "research_plan.checkpoint_questions, source_map.gaps, "
                    "or research_plan.data_gaps.",
                    "Do not invent factual content to fill required sections.",
                ],
                "source_reference_rule": (
                    "Use only source IDs from source_map. Include Source IDs and URLs "
                    "in the Source Appendix."
                ),
                "claim_reference_rules": _claim_reference_rules(evidence_ledger),
                "claim_reference_rule": (
                    "Use only IDs in allowed_claim_ids. Every material factual report "
                    "statement must cite an allowed evidence ledger claim ID in "
                    "[claim_id] form. Populate claim_ids with every allowed claim ID "
                    "cited in markdown."
                ),
                "quality_rules": _synthesis_quality_rules(),
                "source_evidence_context": _synthesis_source_evidence_context(
                    source_map=source_map,
                    source_content=source_content,
                    source_fetch_log=source_fetch_log,
                ),
                "output_schema": "Report",
            }
            run_logger.stage_start("synthesis")
            report = cast(
                Report,
                _run_live_agent(
                    "synthesis",
                    agents.synthesis,
                    _json_prompt("Generate a cited markdown report.", synthesis_payload),
                    agent_runner=agent_runner,
                    run_logger=run_logger,
                ),
            )
            run_logger.stage_end("synthesis")
            report = _repair_missing_report_sections(
                report,
                plan=plan,
                source_map=source_map,
                evidence_ledger=evidence_ledger,
                template_name=template_name,
            )
            try:
                validate_report_traceability(
                    report,
                    evidence_ledger=evidence_ledger,
                    source_map=source_map,
                )
                validate_report_sections(
                    report,
                    template_name=template_name,
                    evidence_ledger=evidence_ledger,
                    source_map=source_map,
                )
            except ReportSectionValidationError as exc:
                report = report.model_copy(update={"status": "draft_needs_revision"})
                _write_report_revision_artifact(
                    run_dir,
                    error=exc,
                    evidence_ledger=evidence_ledger,
                    run_logger=run_logger,
                )
                status = "draft_needs_revision"
            else:
                if qa:
                    run_logger.stage_start("qa")
                    qa_review = _run_qa_review(
                        agents=agents,
                        charter=charter,
                        source_map=source_map,
                        evidence_ledger=evidence_ledger,
                        report=report,
                        agent_runner=agent_runner,
                        run_logger=run_logger,
                    )
                    run_logger.stage_end("qa")
                    status = (
                        "needs_review" if has_high_severity_issues(qa_review) else "report_ready"
                    )
                else:
                    status = "draft_needs_qa"

    write_final_report = _should_write_final_report(
        report=report,
        qa_requested=qa,
        qa_review=qa_review,
    )

    return _write_checkpoint_artifacts(
        run_id=run_id,
        run_dir=run_dir,
        request=request,
        mode=mode,
        mock=mock,
        charter=charter,
        plan=plan,
        sources=sources,
        source_map=source_map,
        source_content=source_content,
        source_fetch_log=source_fetch_log,
        specialist_analyses=specialist_analyses,
        evidence_ledger=evidence_ledger,
        report=report,
        qa_review=qa_review,
        write_final_report=write_final_report,
        status=status,
        started_at=started_at,
        model=model,
        run_type=run_type,
        run_logger=run_logger,
    )


def run_research(
    request: str,
    *,
    mode: str = "standard",
    lens: str | None = None,
    checkpoint_only: bool = False,
    full: bool = False,
    qa: bool = False,
    mock: bool = True,
    runs_dir: str | Path | None = None,
    agent_runner: AgentRunner | None = None,
    model: str | None = None,
    search_client: WebSearchClient | None = None,
    source_fetcher: SourceFetcher | None = None,
) -> ResearchRunResult:
    run_id, run_dir = _create_run_dir(runs_dir)
    started_at = datetime.now(timezone.utc)
    run_type: RunType = "full" if full else "checkpoint"
    run_logger = RunLogger(run_dir, run_id)
    run_logger.stage_start(run_type)
    try:
        result = _run_research_impl(
            request,
            mode=mode,
            lens=lens,
            checkpoint_only=checkpoint_only,
            full=full,
            qa=qa,
            mock=mock,
            runs_dir=runs_dir,
            agent_runner=agent_runner,
            model=model,
            search_client=search_client,
            source_fetcher=source_fetcher,
            run_id=run_id,
            run_dir=run_dir,
            started_at=started_at,
            run_type=run_type,
            run_logger=run_logger,
        )
    except Exception as exc:
        run_logger.error(exc, stage=run_type)
        _write_failure_artifacts(
            run_id=run_id,
            run_dir=run_dir,
            request=request,
            mode=mode,
            lens=lens,
            mock=mock,
            model=model,
            run_type=run_type,
            started_at=started_at,
            error=exc,
            run_logger=run_logger,
        )
        raise
    run_logger.stage_end(run_type, status=result.metadata.status)
    return result
