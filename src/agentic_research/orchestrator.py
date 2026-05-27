from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, cast
from uuid import uuid4

from pydantic import BaseModel

from agentic_research.agents import (
    coerce_agent_output,
    create_agent_set,
    create_mock_charter,
    create_mock_plan,
    discover_mock_sources,
    get_agent_output_type,
    run_agent_sync,
)
from agentic_research.conservative_report import (
    can_apply_supplier_meeting_fallback as _can_apply_supplier_meeting_fallback,
    claim_reference_rules as _claim_reference_rules,
    create_conservative_report as _create_conservative_report,
    repair_missing_report_sections as _repair_missing_report_sections,
    synthesis_quality_rules as _synthesis_quality_rules,
)
from agentic_research.evidence_ledger import (
    EvidenceLedger,
    raise_if_report_has_unsupported_claims,
)
from agentic_research import evidence_pipeline as _evidence_pipeline
from agentic_research.evidence_pipeline import (
    enforce_direct_company_evidence as _enforce_direct_company_evidence,
    merge_specialist_claims as _merge_specialist_claims,
    source_scores_by_id as _source_scores_by_id,
    validate_evidence as _validate_evidence,
)
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
    SourceContent,
    SourceDiscoveryResult,
    SourceFallbackContext,
    SourceFetchLog,
    SourceMap,
    SourceScore,
    SpecialistAnalysis,
    UserFeedback,
)
from agentic_research.report_writer import load_template
from agentic_research.report_writer import render_mock_report
from agentic_research.report_writer import select_report_template_name
from agentic_research.report_writer import write_json_artifact
from agentic_research.report_validation import (
    ReportSectionValidationError,
    required_sections_for_report,
    validate_report_sections,
    validate_report_traceability,
)
from agentic_research.run_logging import RunLogger
from agentic_research.run_artifacts import (
    ResearchRunResult,
    has_blocking_evidence_warnings as _has_blocking_evidence_warnings,
    write_checkpoint_artifacts as _write_checkpoint_artifacts,
    write_failure_artifacts as _write_failure_artifacts,
    write_report_revision_artifact as _write_report_revision_artifact,
)
from agentic_research.qa import (
    has_high_severity_issues,
    merge_qa_reviews,
    run_deterministic_qa_checks,
)
from agentic_research.settings import get_artifact_dir
from agentic_research.source_scoring import build_source_map
from agentic_research.source_context import (
    source_content_payload as _source_content_payload,
    source_fetch_log_payload as _source_fetch_log_payload,
    source_fetch_log_with_fallbacks as _source_fetch_log_with_fallbacks,
    source_map_with_fetch_verification_notes as _source_map_with_fetch_verification_notes,
    source_map_with_fetched_urls as _source_map_with_fetched_urls,
    synthesis_source_evidence_context as _synthesis_source_evidence_context,
    weak_fallback_context_payload as _weak_fallback_context_payload,
    weak_fallback_contexts as _weak_fallback_contexts,
)
from agentic_research.source_ingestion import SourceFetcher, ingest_source_content
from agentic_research.specialists import (
    build_mock_specialist_analyses,
    runnable_specialist_agent_keys,
    select_specialists,
)
from agentic_research.tools.web_search import (
    SearchFailure,
    WebSearchClient,
    build_source_search_queries,
)


AgentRunner = Callable[[str, Any, str], Any]
DIRECT_EVIDENCE_SUFFICIENCY_WARNING = (
    _evidence_pipeline.DIRECT_EVIDENCE_SUFFICIENCY_WARNING
)
_deduplicate_claims = _evidence_pipeline.deduplicate_claims


class _SynthesisQaResult(BaseModel):
    report: Report | None
    qa_review: QAReview | None
    status: str
    write_final_report: bool


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


def _search_failure_gaps(search_failures: list[SearchFailure]) -> list[str]:
    return [
        f"Search query failed: {failure.query} "
        f"({failure.error_type}: {failure.error})"
        for failure in search_failures
    ]


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


def _build_synthesis_payload(
    *,
    charter: ResearchCharter,
    plan: ResearchPlan,
    source_map: SourceMap,
    evidence_ledger: EvidenceLedgerModel,
    specialist_analyses: list[SpecialistAnalysis],
    source_content: list[SourceContent],
    source_fetch_log: SourceFetchLog | None,
    feedback: UserFeedback | None = None,
) -> dict[str, Any]:
    template_name = select_report_template_name(charter)
    required_sections = required_sections_for_report(
        template_name=template_name,
        evidence_ledger=evidence_ledger,
        source_map=source_map,
    )
    section_requirements = [
        "Follow required_sections exactly; do not rename or merge them.",
        "Use the selected_report_template heading sequence as the report outline.",
        "For meeting prep, What We Do Not Know is mandatory.",
        "If Evidence Limitations is listed, explain that the source set is thin.",
    ]
    if feedback is not None:
        section_requirements.extend(
            [
                "Reflect user_feedback priorities in open questions and caveats.",
                "Treat user_feedback as user context, not as source evidence.",
            ]
        )
        gap_sources = (
            "research_plan.checkpoint_questions, source_map.gaps, "
            "research_plan.data_gaps, or user_feedback."
        )
    else:
        gap_sources = (
            "research_plan.checkpoint_questions, source_map.gaps, "
            "or research_plan.data_gaps."
        )
    section_requirements.extend(
        [
            "If needed, write empty-but-honest gap sections from " + gap_sources,
            "Do not invent factual content to fill required sections.",
        ]
    )
    payload = {
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
        "section_requirements": section_requirements,
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
    if feedback is not None:
        payload["user_feedback"] = _user_feedback_prompt_payload(feedback)
    return payload


def _run_qa_with_conservative_revision(
    *,
    agents: Any,
    charter: ResearchCharter,
    plan: ResearchPlan,
    source_map: SourceMap,
    evidence_ledger: EvidenceLedgerModel,
    report: Report,
    agent_runner: AgentRunner | None,
    source_fetch_log: SourceFetchLog | None,
    run_logger: RunLogger | None = None,
) -> tuple[Report, QAReview]:
    qa_review = _run_qa_review(
        agents=agents,
        charter=charter,
        source_map=source_map,
        evidence_ledger=evidence_ledger,
        report=report,
        agent_runner=agent_runner,
        run_logger=run_logger,
    )
    if not has_high_severity_issues(qa_review):
        return report, qa_review

    template_name = select_report_template_name(charter)
    if not _can_apply_supplier_meeting_fallback(charter):
        return report, qa_review

    conservative_report = _create_conservative_report(
        charter=charter,
        plan=plan,
        source_map=source_map,
        evidence_ledger=evidence_ledger,
        source_fetch_log=source_fetch_log,
    )
    try:
        validate_report_traceability(
            conservative_report,
            evidence_ledger=evidence_ledger,
            source_map=source_map,
        )
        validate_report_sections(
            conservative_report,
            template_name=template_name,
            evidence_ledger=evidence_ledger,
            source_map=source_map,
        )
    except ReportSectionValidationError:
        return report, qa_review

    conservative_qa_review = _run_qa_review(
        agents=agents,
        charter=charter,
        source_map=source_map,
        evidence_ledger=evidence_ledger,
        report=conservative_report,
        agent_runner=agent_runner,
        run_logger=run_logger,
    )
    if has_high_severity_issues(conservative_qa_review):
        return report, qa_review
    return conservative_report, conservative_qa_review


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


def _run_synthesis_and_qa(
    *,
    agents: Any,
    charter: ResearchCharter,
    plan: ResearchPlan,
    source_map: SourceMap,
    evidence_ledger: EvidenceLedgerModel,
    specialist_analyses: list[SpecialistAnalysis],
    source_content: list[SourceContent],
    source_fetch_log: SourceFetchLog | None,
    qa: bool,
    agent_runner: AgentRunner | None,
    run_dir: Path,
    run_logger: RunLogger,
    feedback: UserFeedback | None = None,
) -> _SynthesisQaResult:
    if _has_blocking_evidence_warnings(evidence_ledger):
        return _SynthesisQaResult(
            report=None,
            qa_review=None,
            status="evidence_needs_review",
            write_final_report=False,
        )

    template_name = select_report_template_name(charter)
    synthesis_payload = _build_synthesis_payload(
        charter=charter,
        plan=plan,
        source_map=source_map,
        evidence_ledger=evidence_ledger,
        specialist_analyses=specialist_analyses,
        source_content=source_content,
        source_fetch_log=source_fetch_log,
        feedback=feedback,
    )
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

    qa_review = None
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
            report, qa_review = _run_qa_with_conservative_revision(
                agents=agents,
                charter=charter,
                plan=plan,
                source_map=source_map,
                evidence_ledger=evidence_ledger,
                report=report,
                agent_runner=agent_runner,
                source_fetch_log=source_fetch_log,
                run_logger=run_logger,
            )
            run_logger.stage_end("qa")
            status = "needs_review" if has_high_severity_issues(qa_review) else "report_ready"
        else:
            status = "draft_needs_qa"

    return _SynthesisQaResult(
        report=report,
        qa_review=qa_review,
        status=status,
        write_final_report=_should_write_final_report(
            report=report,
            qa_requested=qa,
            qa_review=qa_review,
        ),
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
    source_map = _source_map_with_fetched_urls(source_map, source_content)
    source_map = _source_map_with_fetch_verification_notes(source_map, source_fetch_log)
    sources = list(source_map.sources)
    approved_sources = _approved_sources(source_map)
    weak_fallback_contexts: list[SourceFallbackContext] = []
    feedback_payload = _user_feedback_prompt_payload(feedback)
    evidence_payload = {
        "charter": charter.model_dump(mode="json"),
        "research_plan": plan.model_dump(mode="json"),
        "source_map": source_map.model_dump(mode="json"),
        "approved_sources": [source.model_dump(mode="json") for source in approved_sources],
        "source_content": _source_content_payload(source_content),
        "weak_fallback_context": _weak_fallback_context_payload(weak_fallback_contexts),
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
            "Use source_content chunks first; they are stronger than weak_fallback_context.",
            "Prefer source_content chunks over search snippets and source metadata.",
            "The source_content payload is chunk-limited for model context; "
            "use only the provided chunks for quote_or_excerpt.",
            "When source_content is available, quote_or_excerpt must be a short "
            "verbatim substring copied from the fetched source text, not a paraphrase.",
            "weak_fallback_context is search-result or metadata-only context, "
            "not fetched source text.",
            "No high-confidence claims may come from weak_fallback_context or "
            "snippet-only fallback.",
            "Do not make supplier, strategy, financial, or recent-development claims "
            "from metadata alone.",
            "If only weak_fallback_context is available, produce low-confidence "
            "caveats or no claims.",
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
    evidence_ledger = _validate_evidence(
        evidence_result.claims,
        source_map=source_map,
        source_fetch_log=source_fetch_log,
    )
    evidence_ledger = _enforce_direct_company_evidence(
        evidence_ledger,
        charter=charter,
        source_map=source_map,
    )
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
        source_fetch_log=source_fetch_log,
    )
    evidence_ledger = _enforce_direct_company_evidence(
        evidence_ledger,
        charter=charter,
        source_map=source_map,
    )

    report = None
    qa_review = None
    write_final_report = False
    status = (
        "evidence_needs_review"
        if _has_blocking_evidence_warnings(evidence_ledger)
        else "evidence_ready"
    )
    synthesis_result = _run_synthesis_and_qa(
        agents=agents,
        charter=charter,
        plan=plan,
        source_map=source_map,
        evidence_ledger=evidence_ledger,
        specialist_analyses=specialist_analyses,
        source_content=source_content,
        source_fetch_log=source_fetch_log,
        qa=qa,
        agent_runner=agent_runner,
        run_dir=run_dir,
        run_logger=run_logger,
        feedback=feedback,
    )
    report = synthesis_result.report
    qa_review = synthesis_result.qa_review
    status = synthesis_result.status
    write_final_report = synthesis_result.write_final_report
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
    search_failures = list(search_client.last_failures)
    run_logger.tool_call(
        "web_search",
        status="end",
        result_count=len(raw_search_results),
        failure_count=len(search_failures),
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
    search_failure_gaps = _search_failure_gaps(search_failures)
    if search_failure_gaps:
        source_map.gaps.extend(search_failure_gaps)
    if source_discovery.gaps:
        source_map.gaps.extend(source_discovery.gaps)

    evidence_ledger = None
    report = None
    qa_review = None
    source_content: list[SourceContent] = []
    source_fetch_log: SourceFetchLog | None = None
    specialist_analyses: list[SpecialistAnalysis] = []
    write_final_report = False
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
        source_map = _source_map_with_fetched_urls(source_map, source_content)
        sources = list(source_map.sources)
        approved_sources = _approved_sources(source_map)
        weak_fallback_contexts = _weak_fallback_contexts(
            source_map=source_map,
            raw_search_results=raw_search_results,
            source_content=source_content,
            source_fetch_log=source_fetch_log,
        )
        source_fetch_log = _source_fetch_log_with_fallbacks(
            source_fetch_log,
            weak_fallback_contexts,
        )
        source_map = _source_map_with_fetch_verification_notes(source_map, source_fetch_log)
        sources = list(source_map.sources)
        approved_sources = _approved_sources(source_map)
        evidence_payload = {
            "charter": charter.model_dump(mode="json"),
            "research_plan": plan.model_dump(mode="json"),
            "source_map": source_map.model_dump(mode="json"),
            "approved_sources": [source.model_dump(mode="json") for source in approved_sources],
            "source_content": _source_content_payload(source_content),
            "weak_fallback_context": _weak_fallback_context_payload(weak_fallback_contexts),
            "source_fetch_log": _source_fetch_log_payload(source_fetch_log),
            "source_scores": [
                score.model_dump(mode="json")
                for score in source_map.scores
                if any(source.id == score.source_id for source in approved_sources)
            ],
            "instructions": [
                "Extract evidence claims only from approved_sources.",
                "Use source_content chunks first; they are stronger than weak_fallback_context.",
                "Prefer source_content chunks over search snippets and source metadata.",
                "The source_content payload is chunk-limited for model context; "
                "use only the provided chunks for quote_or_excerpt.",
                "When source_content is available, quote_or_excerpt must be a short "
                "verbatim substring copied from the fetched source text, not a paraphrase.",
                "weak_fallback_context is search-result or metadata-only context, "
                "not fetched source text.",
                "No high-confidence claims may come from weak_fallback_context or "
                "snippet-only fallback.",
                "Do not make supplier, strategy, financial, or recent-development claims "
                "from metadata alone.",
                "If only weak_fallback_context is available, produce low-confidence "
                "caveats or no claims.",
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
        evidence_ledger = _validate_evidence(
            evidence_result.claims,
            source_map=source_map,
            source_fetch_log=source_fetch_log,
        )
        evidence_ledger = _enforce_direct_company_evidence(
            evidence_ledger,
            charter=charter,
            source_map=source_map,
        )
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
            source_fetch_log=source_fetch_log,
        )
        evidence_ledger = _enforce_direct_company_evidence(
            evidence_ledger,
            charter=charter,
            source_map=source_map,
        )
        status = (
            "evidence_needs_review"
            if _has_blocking_evidence_warnings(evidence_ledger)
            else "evidence_ready"
        )
        synthesis_result = _run_synthesis_and_qa(
            agents=agents,
            charter=charter,
            plan=plan,
            source_map=source_map,
            evidence_ledger=evidence_ledger,
            specialist_analyses=specialist_analyses,
            source_content=source_content,
            source_fetch_log=source_fetch_log,
            qa=qa,
            agent_runner=agent_runner,
            run_dir=run_dir,
            run_logger=run_logger,
        )
        report = synthesis_result.report
        qa_review = synthesis_result.qa_review
        status = synthesis_result.status
        write_final_report = synthesis_result.write_final_report

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
