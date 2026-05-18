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
from agentic_research.evidence_ledger import EvidenceLedger
from agentic_research.models import (
    Confidence,
    EvidenceClaim,
    EvidenceExtractionResult,
    EvidenceLedger as EvidenceLedgerModel,
    ResearchCharter,
    ResearchPlan,
    RunMetadata,
    SourceCandidate,
    SourceDiscoveryResult,
    SourceMap,
)
from agentic_research.report_writer import write_checkpoint, write_json_artifact
from agentic_research.settings import get_artifact_dir
from agentic_research.source_scoring import build_source_map
from agentic_research.tools.web_search import WebSearchClient, build_source_search_queries


class ResearchRunResult(BaseModel):
    metadata: RunMetadata
    run_dir: Path
    checkpoint_path: Path
    charter: ResearchCharter
    research_plan: ResearchPlan
    sources: list[SourceCandidate]
    source_map: SourceMap
    evidence_ledger: EvidenceLedgerModel | None = None


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
    evidence_ledger: EvidenceLedgerModel | None = None,
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
    if evidence_ledger is not None:
        write_json_artifact(run_dir / "evidence_ledger.json", evidence_ledger)
    checkpoint_path = write_checkpoint(run_dir, charter, plan, source_map)

    return ResearchRunResult(
        metadata=metadata,
        run_dir=run_dir,
        checkpoint_path=checkpoint_path,
        charter=charter,
        research_plan=plan,
        sources=sources,
        source_map=source_map,
        evidence_ledger=evidence_ledger,
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
    ledger.validate(source_scores=score_lookup)
    return ledger.to_model()


def _validate_evidence(
    claims: list[Any],
    *,
    source_map: SourceMap,
) -> EvidenceLedgerModel:
    ledger = EvidenceLedger(claims)
    ledger.validate(source_scores=_source_scores_by_id(source_map))
    return ledger.to_model()


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
    if qa:
        raise NotImplementedError("Phase 4 does not implement QA runs yet.")
    if not checkpoint_only and not full:
        raise NotImplementedError("Use --checkpoint-only or --full.")

    run_id, run_dir = _create_run_dir(runs_dir)

    if mock:
        charter = create_mock_charter(request, mode=mode, lens=lens)
        plan = create_mock_plan(charter)
        sources = discover_mock_sources(charter)
        source_map = build_source_map(sources, required_source_types=plan.required_source_types)
        evidence_ledger = (
            _extract_mock_evidence(charter=charter, plan=plan, source_map=source_map)
            if full
            else None
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
            evidence_ledger=evidence_ledger,
            status=(
                "evidence_needs_review"
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
    source_map = build_source_map(sources, required_source_types=plan.required_source_types)
    if source_discovery.gaps:
        source_map.gaps.extend(source_discovery.gaps)

    evidence_ledger = None
    status = "checkpoint_ready"
    if full:
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
        evidence_ledger=evidence_ledger,
        status=status,
    )
