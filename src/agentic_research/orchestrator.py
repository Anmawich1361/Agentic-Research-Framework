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
from agentic_research.evidence_ledger import EvidenceLedger, raise_if_report_has_unsupported_claims
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
    SourceCandidate,
    SourceDiscoveryResult,
    SourceMap,
    SpecialistAnalysis,
)
from agentic_research.report_writer import (
    load_template,
    render_mock_report,
    select_report_template_name,
    write_checkpoint,
    write_json_artifact,
    write_report_artifacts,
)
from agentic_research.qa import (
    has_high_severity_issues,
    merge_qa_reviews,
    run_deterministic_qa_checks,
)
from agentic_research.settings import get_artifact_dir
from agentic_research.source_scoring import build_source_map
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
    specialist_analyses: list[SpecialistAnalysis] = Field(default_factory=list)
    evidence_ledger: EvidenceLedgerModel | None = None
    report: Report | None = None
    draft_report_path: Path | None = None
    report_path: Path | None = None
    qa_review: QAReview | None = None


AgentRunner = Callable[[str, Any, str], Any]


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
) -> BaseModel:
    runner = agent_runner or (lambda _key, sdk_agent, sdk_prompt: run_agent_sync(sdk_agent, sdk_prompt))
    output = runner(agent_key, agent, prompt)
    return coerce_agent_output(output, get_agent_output_type(agent_key))


def _create_run_dir(runs_dir: str | Path | None) -> tuple[str, Path]:
    run_id = _new_run_id()
    root = Path(runs_dir) if runs_dir is not None else get_artifact_dir()
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_id, run_dir


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
    specialist_analyses: list[SpecialistAnalysis] | None = None,
    evidence_ledger: EvidenceLedgerModel | None = None,
    report: Report | None = None,
    qa_review: QAReview | None = None,
    write_final_report: bool = True,
    status: str = "checkpoint_ready",
) -> ResearchRunResult:
    metadata = RunMetadata(
        run_id=run_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        request=request,
        status=status,
        mode=mode,
        lens=charter.research_lens,
        mock=mock,
    )

    write_json_artifact(run_dir / "metadata.json", metadata)
    write_json_artifact(run_dir / "charter.json", charter)
    write_json_artifact(run_dir / "research_plan.json", plan)
    write_json_artifact(run_dir / "sources.json", sources)
    write_json_artifact(run_dir / "source_map.json", source_map)
    if specialist_analyses:
        write_json_artifact(run_dir / "specialist_analyses.json", specialist_analyses)
    if evidence_ledger is not None:
        write_json_artifact(run_dir / "evidence_ledger.json", evidence_ledger)
    draft_report_path = None
    report_path = None
    if report is not None:
        draft_report_path, report_path = write_report_artifacts(
            run_dir,
            report,
            write_final=write_final_report,
        )
    if qa_review is not None:
        write_json_artifact(run_dir / "qa_review.json", qa_review)
    checkpoint_path = write_checkpoint(run_dir, charter, plan, source_map, mock=mock)

    return ResearchRunResult(
        metadata=metadata,
        run_dir=run_dir,
        checkpoint_path=checkpoint_path,
        charter=charter,
        research_plan=plan,
        sources=sources,
        source_map=source_map,
        specialist_analyses=specialist_analyses or [],
        evidence_ledger=evidence_ledger,
        report=report,
        draft_report_path=draft_report_path,
        report_path=report_path,
        qa_review=qa_review,
    )


def _source_scores_by_id(source_map: SourceMap) -> dict[str, Any]:
    return {score.source_id: score for score in source_map.scores}


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
        claims.append(
            EvidenceClaim(
                id=f"claim_{index}",
                claim=f"{source.title} is relevant to researching {charter.target}.",
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
    claims: list[Any],
    *,
    source_map: SourceMap,
) -> EvidenceLedgerModel:
    ledger = EvidenceLedger(claims)
    ledger.validate(source_scores=_source_scores_by_id(source_map), source_map=source_map)
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
        analysis = cast(
            SpecialistAnalysis,
            _run_live_agent(
                specialist_key,
                agent,
                _json_prompt(f"Run {specialist_key} specialist analysis.", payload),
                agent_runner=agent_runner,
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
    specialist_claims = [
        claim
        for analysis in specialist_analyses
        for claim in analysis.evidence_claims
    ]
    if not specialist_claims:
        return evidence_ledger
    return _validate_evidence(
        [*evidence_ledger.claims, *specialist_claims],
        source_map=source_map,
    )


_BRACKET_REFERENCE_RE = re.compile(r"\[([A-Za-z][A-Za-z0-9_-]*)\]")
_SOURCE_ID_REFERENCE_RE = re.compile(r"\b(src_[A-Za-z0-9_-]+)\b")


class ReportSectionValidationError(ValueError):
    def __init__(self, missing_sections: list[str]) -> None:
        self.missing_sections = missing_sections
        super().__init__(
            f"Report is missing required sections: {', '.join(missing_sections)}"
        )


def _markdown_claim_references(markdown: str, known_claim_ids: set[str]) -> set[str]:
    references = set(_BRACKET_REFERENCE_RE.findall(markdown))
    return {
        reference
        for reference in references
        if reference in known_claim_ids or reference.startswith("claim_")
    }


def _markdown_source_references(markdown: str) -> set[str]:
    return set(_SOURCE_ID_REFERENCE_RE.findall(markdown))


def _validate_report_traceability(
    report: Report,
    *,
    evidence_ledger: EvidenceLedgerModel,
    source_map: SourceMap,
) -> None:
    allowed_claim_ids = {claim.id for claim in evidence_ledger.claims}
    markdown_claim_ids = _markdown_claim_references(report.markdown, allowed_claim_ids)
    report.claim_ids = sorted(set(report.claim_ids).union(markdown_claim_ids))
    unknown_claim_ids = sorted(claim_id for claim_id in report.claim_ids if claim_id not in allowed_claim_ids)
    if unknown_claim_ids:
        raise ValueError(
            f"Report contains unknown evidence claim references: {', '.join(unknown_claim_ids)}"
        )

    allowed_source_ids = {source.id for source in source_map.sources}
    report_source_ids = set(report.source_ids).union(_markdown_source_references(report.markdown))
    unknown = sorted(source_id for source_id in report_source_ids if source_id not in allowed_source_ids)
    if unknown:
        raise ValueError(f"Report contains unknown source references: {', '.join(unknown)}")


def _missing_report_sections(report: Report) -> list[str]:
    markdown = report.markdown.lower()
    required_terms = [
        "executive summary",
        "key findings",
        "competitors",
        "risks",
        "open questions",
        "source appendix",
    ]
    missing = [term for term in required_terms if term not in markdown]
    if "business overview" not in markdown and "industry overview" not in markdown:
        missing.append("business or industry overview")
    return missing


def _validate_report_sections(report: Report) -> None:
    missing = _missing_report_sections(report)
    if missing:
        raise ReportSectionValidationError(missing)


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


def _repair_missing_report_sections(
    report: Report,
    *,
    plan: ResearchPlan,
    source_map: SourceMap,
) -> Report:
    missing = _missing_report_sections(report)
    if "open questions" not in missing:
        return report

    open_questions = _unique_nonempty(
        [
            *plan.checkpoint_questions,
            *source_map.gaps,
            *plan.data_gaps,
        ]
    )
    if not open_questions:
        open_questions = [
            "No open questions were identified from checkpoint questions, "
            "source-map gaps, or plan data gaps."
        ]

    markdown = (
        f"{report.markdown.rstrip()}\n\n"
        "## Open Questions\n"
        f"{_format_markdown_bullets(open_questions)}\n"
    )
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
    _validate_report_traceability(report, evidence_ledger=evidence_ledger, source_map=source_map)
    _validate_report_sections(report)
    return report


def _run_qa_review(
    *,
    agents: Any,
    charter: ResearchCharter,
    source_map: SourceMap,
    evidence_ledger: EvidenceLedgerModel,
    report: Report,
    agent_runner: AgentRunner | None,
) -> QAReview:
    deterministic_review = run_deterministic_qa_checks(
        source_map=source_map,
        evidence_ledger=evidence_ledger,
        draft_report=report,
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
        ),
    )
    return merge_qa_reviews(deterministic_review, agent_review)


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
) -> ResearchRunResult:
    """Run the checkpoint workflow and write local artifacts."""
    if qa and not full:
        raise NotImplementedError("Use --full with --qa.")
    if not checkpoint_only and not full:
        raise NotImplementedError("Use --checkpoint-only or --full.")

    run_id, run_dir = _create_run_dir(runs_dir)

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
            if evidence_ledger is not None and not evidence_ledger.validation_warnings
            else None
        )
        qa_review = (
            run_deterministic_qa_checks(
                source_map=source_map,
                evidence_ledger=evidence_ledger,
                draft_report=report,
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
                if evidence_ledger is not None and evidence_ledger.validation_warnings
                else "evidence_ready"
                if evidence_ledger is not None
                else "checkpoint_ready"
            ),
        )

    search_client = search_client or WebSearchClient()
    agents = create_agent_set(model=model, search_client=search_client)
    intake_payload = {
        "request": request,
        "mode": mode,
        "lens_override": lens,
        "output_schema": "ResearchCharter",
    }
    charter = cast(
        ResearchCharter,
        _run_live_agent(
            "intake",
            agents.intake,
            _json_prompt("Create a research charter for this request.", intake_payload),
            agent_runner=agent_runner,
        ),
    )

    planner_payload = {
        "charter": charter.model_dump(mode="json"),
        "output_schema": "ResearchPlan",
    }
    plan = cast(
        ResearchPlan,
        _run_live_agent(
            "planner",
            agents.planner,
            _json_prompt("Create a checkpoint research plan from this charter.", planner_payload),
            agent_runner=agent_runner,
        ),
    )

    source_search_queries = build_source_search_queries(charter, plan)
    raw_search_results = search_client.search_many(source_search_queries)
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
    source_discovery = cast(
        SourceDiscoveryResult,
        _run_live_agent(
            "source_discovery",
            agents.source_discovery,
            _json_prompt("Discover and classify checkpoint sources.", source_discovery_payload),
            agent_runner=agent_runner,
        ),
    )
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
    specialist_analyses: list[SpecialistAnalysis] = []
    status = "checkpoint_ready"
    if full:
        selected_specialists = select_specialists(charter, plan)
        approved_sources = _approved_sources(source_map)
        evidence_payload = {
            "charter": charter.model_dump(mode="json"),
            "research_plan": plan.model_dump(mode="json"),
            "source_map": source_map.model_dump(mode="json"),
            "approved_sources": [source.model_dump(mode="json") for source in approved_sources],
            "source_scores": [
                score.model_dump(mode="json")
                for score in source_map.scores
                if any(source.id == score.source_id for source in approved_sources)
            ],
            "instructions": [
                "Extract evidence claims only from approved_sources.",
                "Every fact claim must include source_id or source_url.",
                "Use high confidence only for authority score >= 4 sources.",
                "Do not write a report.",
            ],
            "output_schema": "EvidenceExtractionResult",
        }
        evidence_result = cast(
            EvidenceExtractionResult,
            _run_live_agent(
                "evidence_extraction",
                agents.evidence_extraction,
                _json_prompt("Extract evidence claims from approved sources.", evidence_payload),
                agent_runner=agent_runner,
            ),
        )
        evidence_ledger = _validate_evidence(evidence_result.claims, source_map=source_map)
        status = "evidence_needs_review" if evidence_ledger.validation_warnings else "evidence_ready"
        if not evidence_ledger.validation_warnings:
            specialist_analyses = _run_specialist_analyses(
                agents=agents,
                charter=charter,
                plan=plan,
                source_map=source_map,
                evidence_ledger=evidence_ledger,
                selected_specialists=selected_specialists,
                agent_runner=agent_runner,
            )
        evidence_ledger = _merge_specialist_claims(
            evidence_ledger,
            specialist_analyses,
            source_map=source_map,
        )
        status = "evidence_needs_review" if evidence_ledger.validation_warnings else "evidence_ready"
        if not evidence_ledger.validation_warnings:
            template_name = select_report_template_name(charter)
            synthesis_payload = {
                "charter": charter.model_dump(mode="json"),
                "research_plan": plan.model_dump(mode="json"),
                "source_map": source_map.model_dump(mode="json"),
                "evidence_ledger": evidence_ledger.model_dump(mode="json"),
                "specialist_analyses": [
                    analysis.model_dump(mode="json") for analysis in specialist_analyses
                ],
                "selected_report_template": {
                    "name": template_name,
                    "markdown": load_template(template_name),
                },
                "required_sections": [
                    "Executive Summary",
                    "Key Findings",
                    "Business or Industry Overview",
                    "Competitors when relevant",
                    "Risks",
                    "Open Questions",
                    "Source Appendix",
                ],
                "section_requirements": [
                    "Open Questions is mandatory even if there are few known gaps.",
                    "If needed, write an empty-but-honest Open Questions section from "
                    "research_plan.checkpoint_questions, source_map.gaps, or "
                    "research_plan.data_gaps.",
                    "Do not invent factual content to fill required sections.",
                ],
                "source_reference_rule": (
                    "Use only source IDs from source_map. Include Source IDs and URLs "
                    "in the Source Appendix."
                ),
                "claim_reference_rule": (
                    "Every material factual report statement must cite an evidence "
                    "ledger claim ID in [claim_id] form. Populate claim_ids with every "
                    "claim ID cited in markdown."
                ),
                "output_schema": "Report",
            }
            report = cast(
                Report,
                _run_live_agent(
                    "synthesis",
                    agents.synthesis,
                    _json_prompt("Generate a cited markdown report.", synthesis_payload),
                    agent_runner=agent_runner,
                ),
            )
            report = _repair_missing_report_sections(
                report,
                plan=plan,
                source_map=source_map,
            )
            _validate_report_traceability(
                report,
                evidence_ledger=evidence_ledger,
                source_map=source_map,
            )
            try:
                _validate_report_sections(report)
            except ReportSectionValidationError:
                report = report.model_copy(update={"status": "draft_needs_revision"})
                status = "draft_needs_revision"
            else:
                if qa:
                    qa_review = _run_qa_review(
                        agents=agents,
                        charter=charter,
                        source_map=source_map,
                        evidence_ledger=evidence_ledger,
                        report=report,
                        agent_runner=agent_runner,
                    )
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
        specialist_analyses=specialist_analyses,
        evidence_ledger=evidence_ledger,
        report=report,
        qa_review=qa_review,
        write_final_report=write_final_report,
        status=status,
    )
