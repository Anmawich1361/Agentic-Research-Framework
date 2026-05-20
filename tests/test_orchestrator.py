import json
from pathlib import Path
from typing import Any

from agentic_research.models import (
    EvidenceClaim,
    EvidenceExtractionResult,
    QAIssue,
    QAReview,
    Report,
    ResearchCharter,
    ResearchPlan,
    SourceChunk,
    SourceCandidate,
    SourceContent,
    SourceFetchLog,
    SourceFetchResult,
    SourceDiscoveryResult,
    SourceMap,
    SourceScore,
    SpecialistAnalysis,
    UserFeedback,
)
from agentic_research.orchestrator import (
    _deduplicate_claims,
    _source_content_payload,
    _synthesis_source_evidence_context,
    _validate_evidence,
    continue_research,
    run_research,
    save_user_feedback,
)
from agentic_research.source_ingestion import SourceHttpResponse
from agentic_research.tools.web_search import SearchResult, StaticSearchProvider, WebSearchClient


def _fetcher_with_supplier_content(url: str, timeout_seconds: float) -> SourceHttpResponse:
    return SourceHttpResponse(
        url=url,
        status_code=200,
        headers={"content-type": "text/html; charset=utf-8"},
        text=(
            "<html><head><title>Supplier standards</title></head>"
            "<body><main><p>Costco requires suppliers to meet delivery windows.</p>"
            "<p>Suppliers must provide accurate item data.</p></main></body></html>"
        ),
    )


def _failing_source_fetcher(url: str, timeout_seconds: float) -> SourceHttpResponse:
    raise TimeoutError("network disabled in tests")


def _json_payload_from_prompt(prompt: str) -> dict[str, Any]:
    payload = prompt.split("```json\n", 1)[1].split("\n```", 1)[0]
    parsed = json.loads(payload)
    assert isinstance(parsed, dict)
    return parsed


def test_deduplicate_claims_drops_near_duplicate_specialist_claim_before_renaming() -> None:
    base_campaign_claim = EvidenceClaim(
        id="c12",
        claim="Costco said its first targeted media campaign achieved two to three times the typical return on ad spend.",
        claim_type="fact",
        source_id="s6",
        source_url="https://example.com/transcript",
        confidence="medium",
        report_section="supplier_context",
        quote_or_excerpt="two to three times the return on ad spend",
    )
    conflicting_id_claim = EvidenceClaim(
        id="e13",
        claim="Costco sells groceries and general merchandise.",
        claim_type="fact",
        source_id="s6",
        source_url="https://example.com/transcript",
        confidence="medium",
        report_section="overview",
    )
    specialist_duplicate = SpecialistAnalysis(
        specialist="competitor",
        summary="Specialist analysis.",
        evidence_claims=[
            EvidenceClaim(
                id="e13",
                claim="Costco said its first targeted media campaign achieved two to three times the typical return on ad spend.",
                claim_type="fact",
                source_id="s6",
                source_url="https://example.com/transcript",
                confidence="medium",
                report_section="supplier_context",
                quote_or_excerpt="two to three times the return on ad spend",
            )
        ],
    )

    claims, warnings = _deduplicate_claims(
        [base_campaign_claim, conflicting_id_claim],
        [specialist_duplicate],
    )

    assert [claim.id for claim in claims] == ["c12", "e13"]
    assert any("Deduplicated near-duplicate evidence claim ID e13" in warning for warning in warnings)


def test_source_content_payload_bounds_chunks_for_agent_context() -> None:
    content = SourceContent(
        source_id="src_large",
        url="https://example.com/large",
        content_type="text/html",
        title="Large source",
        text="x" * 10000,
        excerpt="Large source excerpt",
        chunks=[
            SourceChunk(
                source_id="src_large",
                url="https://example.com/large",
                chunk_id=f"src_large_chunk_{index}",
                index=index,
                text="x" * 2000,
            )
            for index in range(10)
        ],
    )

    payload = _source_content_payload(
        [content],
        max_total_chars=2500,
        max_chunks_per_source=3,
        max_chunk_chars=1000,
    )

    assert "text" not in payload[0]
    assert len(payload[0]["chunks"]) == 3
    assert sum(len(chunk["text"]) for chunk in payload[0]["chunks"]) == 2500


def test_source_content_payload_skips_low_information_filing_preamble() -> None:
    content = SourceContent(
        source_id="src_filing",
        url="https://example.com/filing",
        content_type="text/html",
        title="SEC filing",
        text="",
        chunks=[
            SourceChunk(
                source_id="src_filing",
                url="https://example.com/filing",
                chunk_id="src_filing_chunk_1",
                index=0,
                text=(
                    "0000909832\nus-gaap:CommonStockMember\n"
                    "http://fasb.org/us-gaap/2024#Assets\n0000909832\n"
                )
                * 12,
            ),
            SourceChunk(
                source_id="src_filing",
                url="https://example.com/filing",
                chunk_id="src_filing_chunk_2",
                index=1,
                text=(
                    "Costco operates membership warehouses and sells merchandise "
                    "across food, non-food, and services categories. The business "
                    "section discusses warehouses, membership renewal, and net sales."
                ),
            ),
        ],
    )

    payload = _source_content_payload([content], max_chunks_per_source=1)

    assert payload[0]["chunks"][0]["chunk_id"] == "src_filing_chunk_2"


def test_synthesis_source_evidence_context_warns_when_direct_sources_do_not_fetch() -> None:
    source_map = SourceMap(
        sources=[
            SourceCandidate(
                id="s_primary",
                title="Costco investor relations",
                publisher="Costco",
                url="https://investor.costco.com",
                source_type="investor_material",
                bias_risk="low",
                relevance_rationale="Direct company source.",
                recommended_uses=["primary current support"],
            ),
            SourceCandidate(
                id="s_secondary",
                title="Costco transcript index",
                publisher="Transcript Site",
                url="https://example.com/transcripts",
                source_type="earnings_transcript",
                bias_risk="medium",
                relevance_rationale="Secondary transcript index.",
                recommended_uses=["recent commentary"],
            ),
        ],
        scores=[
            SourceScore(
                source_id="s_primary",
                authority_score=5,
                relevance_score=5,
                recency_score=4,
                coverage_score=4,
                bias_risk="low",
                final_score=4.6,
                include=True,
            ),
            SourceScore(
                source_id="s_secondary",
                authority_score=3,
                relevance_score=4,
                recency_score=4,
                coverage_score=3,
                bias_risk="medium",
                final_score=3.5,
                include=True,
            ),
        ],
        gaps=[],
    )
    source_content = [
        SourceContent(
            source_id="s_secondary",
            url="https://example.com/transcripts",
            content_type="text/html",
            title="Costco transcript index",
            text="Secondary transcript page.",
            excerpt="Secondary transcript page.",
        )
    ]
    fetch_log = SourceFetchLog(
        results=[
            SourceFetchResult(
                source_id="s_primary",
                url="https://investor.costco.com",
                status="failed",
                error="No readable text extracted.",
            ),
            SourceFetchResult(
                source_id="s_secondary",
                url="https://example.com/transcripts",
                status="fetched",
                content_type="text/html",
            ),
        ]
    )

    context = _synthesis_source_evidence_context(
        source_map=source_map,
        source_content=source_content,
        source_fetch_log=fetch_log,
    )

    assert context["fetched_source_ids"] == ["s_secondary"]
    assert context["fetched_direct_source_ids"] == []
    assert context["candidate_direct_source_ids"] == ["s_primary"]
    assert context["failed_or_skipped_source_ids"] == ["s_primary"]
    assert context["secondary_or_indirect_only"] is True
    assert any("direct source content" in warning for warning in context["warnings"])


def test_validate_evidence_drops_claims_without_usable_source_before_synthesis() -> None:
    source_map = SourceMap(
        sources=[
            SourceCandidate(
                id="src_good",
                title="Good source",
                publisher="Example",
                url="https://example.com/good",
                source_type="primary_company",
                bias_risk="medium",
                relevance_rationale="Useful source.",
                recommended_uses=["overview"],
            ),
            SourceCandidate(
                id="src_empty",
                title="Empty URL source",
                publisher="Example",
                url="",
                source_type="news",
                bias_risk="medium",
                relevance_rationale="No URL.",
                recommended_uses=["gap"],
            ),
        ],
        scores=[
            SourceScore(
                source_id="src_good",
                authority_score=4,
                relevance_score=4,
                recency_score=4,
                coverage_score=4,
                bias_risk="medium",
                final_score=4,
                include=True,
            ),
            SourceScore(
                source_id="src_empty",
                authority_score=3,
                relevance_score=3,
                recency_score=3,
                coverage_score=2,
                bias_risk="medium",
                final_score=3,
                include=True,
            ),
        ],
        gaps=[],
    )

    ledger = _validate_evidence(
        [
            EvidenceClaim(
                id="claim_good",
                claim="Costco publishes supplier standards.",
                claim_type="fact",
                confidence="high",
                report_section="overview",
                source_id="src_good",
                source_url="https://example.com/good",
            ),
            EvidenceClaim(
                id="claim_missing",
                claim="No category-specific source was identified.",
                claim_type="fact",
                confidence="high",
                report_section="open_questions",
            ),
            EvidenceClaim(
                id="claim_empty",
                claim="A news source would be useful but has no URL.",
                claim_type="fact",
                confidence="high",
                report_section="recent_developments",
                source_id="src_empty",
            ),
            EvidenceClaim(
                id="claim_metadata",
                claim="The source describes Costco's investor relations page.",
                claim_type="fact",
                confidence="high",
                report_section="overview",
                source_id="src_good",
                source_url="https://example.com/good",
            ),
        ],
        source_map=source_map,
    )

    assert [claim.id for claim in ledger.claims] == ["claim_good"]
    assert any(
        "Dropped unsupported evidence claim ID claim_missing" in warning
        for warning in ledger.validation_warnings
    )
    assert any(
        "Dropped unsupported evidence claim ID claim_empty" in warning
        for warning in ledger.validation_warnings
    )
    assert any(
        "Dropped unsupported evidence claim ID claim_metadata" in warning
        for warning in ledger.validation_warnings
    )
    assert not any("fact claim must include" in warning for warning in ledger.validation_warnings)


def test_continue_from_mock_checkpoint_uses_saved_feedback(tmp_path: Path) -> None:
    checkpoint = run_research(
        "Research Costco before a supplier meeting",
        mock=True,
        checkpoint_only=True,
        runs_dir=tmp_path,
        lens="sales",
    )
    feedback = UserFeedback(
        answered_checkpoint_questions=[
            {"question": "Which supplier category matters?", "answer": "Frozen food."}
        ],
        user_notes="Prepare this for a supplier conversation.",
        priority_topics=["vendor onboarding"],
    )
    saved_path = save_user_feedback(checkpoint.run_dir, feedback)

    continued = continue_research(
        checkpoint.metadata.run_id,
        runs_dir=tmp_path,
        mock=True,
    )

    assert saved_path == checkpoint.run_dir / "user_feedback.json"
    assert saved_path.exists()
    assert continued.metadata.run_id == checkpoint.metadata.run_id
    assert continued.metadata.status == "draft_needs_qa"
    assert continued.report is not None
    assert (checkpoint.run_dir / "draft_report.md").exists()


def test_continue_includes_user_feedback_and_excludes_rejected_sources(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    synthesis_prompt = ""

    def fake_checkpoint_agent_runner(agent_key: str, agent: Any, prompt: str) -> Any:
        calls.append(agent_key)
        if agent_key == "intake":
            return ResearchCharter(
                target="Costco",
                target_type="company",
                research_lens="sales",
                depth="brief",
                deliverable="meeting_prep_brief",
                key_questions=["What should suppliers know?"],
            )
        if agent_key == "planner":
            return ResearchPlan(
                research_questions=["What should suppliers understand?"],
                report_sections=["overview"],
                required_source_types=["primary_company"],
                checkpoint_questions=["Which supplier category matters?"],
            )
        if agent_key == "source_discovery":
            return SourceDiscoveryResult(
                sources=[
                    SourceCandidate(
                        id="src_keep",
                        title="Costco supplier page",
                        publisher="Costco",
                        url="https://example.com/keep",
                        source_type="primary_company",
                        bias_risk="medium",
                        relevance_rationale="Supplier context.",
                        recommended_uses=["supplier meeting"],
                    ),
                    SourceCandidate(
                        id="src_rejected",
                        title="Rejected source",
                        publisher="Example",
                        url="https://example.com/rejected",
                        source_type="news",
                        bias_risk="high",
                        relevance_rationale="User rejected this source.",
                        recommended_uses=["do not use"],
                    ),
                ]
            )
        raise AssertionError(f"Unexpected checkpoint agent call: {agent_key}")

    checkpoint = run_research(
        "Research Costco before a supplier meeting",
        checkpoint_only=True,
        mock=False,
        runs_dir=tmp_path,
        agent_runner=fake_checkpoint_agent_runner,
        search_client=WebSearchClient(provider=StaticSearchProvider({})),
    )
    save_user_feedback(
        checkpoint.run_dir,
        UserFeedback(
            answered_checkpoint_questions=[
                {
                    "question": "Which supplier category matters?",
                    "answer": "Frozen food.",
                }
            ],
            rejected_source_ids=["src_rejected"],
            approved_source_ids=["src_keep"],
            user_notes="Focus on frozen-food supplier readiness.",
            priority_topics=["cold-chain reliability"],
        ),
    )
    calls.clear()

    def fake_continue_agent_runner(agent_key: str, agent: Any, prompt: str) -> Any:
        nonlocal synthesis_prompt
        calls.append(agent_key)
        if agent_key == "evidence_extraction":
            assert "user_feedback" in prompt
            assert "Frozen food" in prompt
            assert "src_keep" in prompt
            assert "src_rejected" not in prompt
            return EvidenceExtractionResult(
                claims=[
                    EvidenceClaim(
                        id="claim_keep",
                        claim="Costco publishes supplier contact information.",
                        claim_type="fact",
                        source_id="src_keep",
                        source_url="https://example.com/keep",
                        confidence="medium",
                        report_section="what_we_know",
                        quote_or_excerpt="Supplier Contact",
                    )
                ]
            )
        if agent_key in {"news", "competitor", "risk"}:
            assert "user_feedback" in prompt
            return SpecialistAnalysis(
                specialist=agent_key,
                summary="Source-bound analysis.",
                source_ids=["src_keep"],
            )
        if agent_key == "synthesis":
            synthesis_prompt = prompt
            assert "user_feedback" in prompt
            assert "cold-chain reliability" in prompt
            assert "src_rejected" not in prompt
            return Report(
                title="Costco Supplier Meeting Prep",
                markdown=(
                    "# Costco Supplier Meeting Prep\n\n"
                    "## Executive Summary\nEvidence-backed summary. [claim_keep]\n\n"
                    "## Context for Meeting\nContext.\n\n"
                    "## What We Know\n- Costco publishes supplier contact information. "
                    "[claim_keep]\n\n"
                    "## What We Do Not Know\n- Category-specific requirements.\n\n"
                    "## Supplier/Buyer Angle\nCaveated angle.\n\n"
                    "## Questions to Ask\n- Which frozen-food lane matters?\n\n"
                    "## Risks and Watchouts\n- Cold-chain requirements are unverified.\n\n"
                    "## Evidence Limitations\nOnly one approved source supports this brief.\n\n"
                    "## Source Appendix\n- Costco supplier page (src_keep)\n"
                ),
                source_ids=["src_keep"],
            )
        raise AssertionError(f"Unexpected continue agent call: {agent_key}")

    result = continue_research(
        checkpoint.metadata.run_id,
        runs_dir=tmp_path,
        mock=False,
        agent_runner=fake_continue_agent_runner,
        source_fetcher=_fetcher_with_supplier_content,
        search_client=WebSearchClient(provider=StaticSearchProvider({})),
    )

    assert calls == ["evidence_extraction", "news", "competitor", "risk", "synthesis"]
    assert "cold-chain reliability" in synthesis_prompt
    assert result.report is not None
    assert result.report.source_ids == ["src_keep"]
    source_map = json.loads((checkpoint.run_dir / "source_map.json").read_text())
    assert [source["id"] for source in source_map["sources"]] == ["src_keep"]


def test_mock_checkpoint_metadata_and_structured_log_include_run_lifecycle(
    tmp_path: Path,
) -> None:
    result = run_research(
        "Research Nvidia before an investor meeting",
        mock=True,
        checkpoint_only=True,
        runs_dir=tmp_path,
        model="mock-model",
    )

    run_dir = tmp_path / result.metadata.run_id
    metadata = json.loads((run_dir / "metadata.json").read_text())
    log_events = [
        json.loads(line)
        for line in (run_dir / "run_log.jsonl").read_text().splitlines()
    ]

    assert metadata["started_at"]
    assert metadata["completed_at"]
    assert metadata["duration_seconds"] >= 0
    assert metadata["model"] == "mock-model"
    assert metadata["run_type"] == "checkpoint"
    assert metadata["status"] == "checkpoint_ready"
    assert metadata["status_reason"]
    assert any(event["event"] == "stage_start" and event["stage"] == "checkpoint" for event in log_events)
    assert any(event["event"] == "stage_end" and event["stage"] == "checkpoint" for event in log_events)
    assert any(event["event"] == "artifact_written" for event in log_events)


def test_live_checkpoint_failure_writes_failure_artifacts_and_no_final_report(
    tmp_path: Path,
) -> None:
    def failing_agent_runner(agent_key: str, agent: Any, prompt: str) -> Any:
        if agent_key == "intake":
            return ResearchCharter(
                target="Costco",
                target_type="company",
                research_lens="sales",
                depth="brief",
                deliverable="meeting_prep_brief",
                key_questions=["What should suppliers know?"],
            )
        raise RuntimeError(f"{agent_key} failed intentionally")

    try:
        run_research(
            "Research Costco before a supplier meeting",
            checkpoint_only=True,
            mock=False,
            runs_dir=tmp_path,
            agent_runner=failing_agent_runner,
            search_client=WebSearchClient(provider=StaticSearchProvider({})),
        )
    except RuntimeError as exc:
        assert "planner failed intentionally" in str(exc)
    else:
        raise AssertionError("Expected live checkpoint failure to be re-raised")

    run_dirs = [path for path in tmp_path.iterdir() if path.is_dir()]
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    expected_files = {
        "metadata.json",
        "error.json",
        "failure_report.md",
        "run_log.jsonl",
    }
    metadata = json.loads((run_dir / "metadata.json").read_text())
    error = json.loads((run_dir / "error.json").read_text())
    failure_report = (run_dir / "failure_report.md").read_text()
    log_events = [
        json.loads(line)
        for line in (run_dir / "run_log.jsonl").read_text().splitlines()
    ]

    assert expected_files == {path.name for path in run_dir.iterdir() if path.is_file()}
    assert metadata["status"] == "failed"
    assert metadata["status_reason"] == "RuntimeError: planner failed intentionally"
    assert metadata["run_type"] == "checkpoint"
    assert metadata["completed_at"]
    assert metadata["duration_seconds"] >= 0
    assert error["error_type"] == "RuntimeError"
    assert error["message"] == "planner failed intentionally"
    assert "planner failed intentionally" in failure_report
    assert not (run_dir / "report.md").exists()
    assert any(event["event"] == "error" for event in log_events)


def test_mock_orchestrator_checkpoint_run_creates_expected_artifacts(tmp_path: Path) -> None:
    result = run_research(
        "Research Nvidia before an investor meeting",
        mock=True,
        checkpoint_only=True,
        runs_dir=tmp_path,
    )

    run_dir = tmp_path / result.metadata.run_id
    expected_files = {
        "metadata.json",
        "charter.json",
        "research_plan.json",
        "sources.json",
        "source_map.json",
        "checkpoint.md",
        "run_log.jsonl",
    }

    assert run_dir.is_dir()
    assert expected_files == {path.name for path in run_dir.iterdir() if path.is_file()}
    assert result.checkpoint_path == run_dir / "checkpoint.md"

    metadata = json.loads((run_dir / "metadata.json").read_text())
    charter = json.loads((run_dir / "charter.json").read_text())
    checkpoint = (run_dir / "checkpoint.md").read_text()

    assert metadata["request"] == "Research Nvidia before an investor meeting"
    assert metadata["status"] == "checkpoint_ready"
    assert metadata["mock"] is True
    assert charter["target"] == "Nvidia"
    assert "Research Checkpoint: Nvidia" in checkpoint
    assert "Questions Before Deep Research" in checkpoint


def test_live_checkpoint_run_uses_agents_and_writes_artifacts(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def fake_agent_runner(agent_key: str, agent: Any, prompt: str) -> Any:
        calls.append((agent_key, prompt))
        if agent_key == "intake":
            return ResearchCharter(
                target="Costco",
                target_type="company",
                research_lens="sales",
                depth="standard",
                deliverable="meeting_prep_brief",
                key_questions=["What should we understand before the supplier meeting?"],
                geography="United States",
                time_horizon="current and recent developments",
            )
        if agent_key == "planner":
            return ResearchPlan(
                research_questions=["What does Costco prioritize with suppliers?"],
                report_sections=["overview", "supplier_context", "open_questions"],
                required_source_types=["primary_company", "news"],
                checkpoint_questions=["Which supplier category should be prioritized?"],
                likely_specialists=[],
                known_risks=[],
                data_gaps=["Supplier category not specified."],
            )
        if agent_key == "source_discovery":
            return SourceDiscoveryResult(
                sources=[
                    SourceCandidate(
                        id="src_costco_primary",
                        title="Costco supplier information",
                        publisher="Costco",
                        url="https://www.costco.com/suppliers.html",
                        source_type="primary_company",
                        publication_date="2026-01-10",
                        relevance_rationale="Primary source for supplier expectations.",
                        recommended_uses=["supplier context"],
                        bias_risk="high",
                    ),
                    SourceCandidate(
                        id="src_costco_news",
                        title="Recent Costco supplier coverage",
                        publisher="Mock News",
                        url="https://example.com/costco-supplier-news",
                        source_type="news",
                        publication_date="2026-04-01",
                        relevance_rationale="Recent context for meeting prep.",
                        recommended_uses=["recent developments"],
                        bias_risk="medium",
                    ),
                ],
                gaps=[],
            )
        raise AssertionError(f"Unexpected agent call: {agent_key}")

    result = run_research(
        "Research Costco before a supplier meeting",
        checkpoint_only=True,
        mock=False,
        runs_dir=tmp_path,
        agent_runner=fake_agent_runner,
        source_fetcher=_failing_source_fetcher,
        search_client=WebSearchClient(provider=StaticSearchProvider({})),
    )

    assert [call[0] for call in calls] == ["intake", "planner", "source_discovery"]
    assert result.metadata.mock is False
    assert result.charter.target == "Costco"
    assert result.research_plan.required_source_types == ["primary_company", "news"]
    assert [source.id for source in result.sources] == ["src_costco_primary", "src_costco_news"]
    assert result.source_map.scores[0].source_id in {"src_costco_primary", "src_costco_news"}
    assert (tmp_path / result.metadata.run_id / "checkpoint.md").exists()

    metadata = json.loads((tmp_path / result.metadata.run_id / "metadata.json").read_text())
    checkpoint = (tmp_path / result.metadata.run_id / "checkpoint.md").read_text()
    source_map = json.loads((tmp_path / result.metadata.run_id / "source_map.json").read_text())
    assert metadata["mock"] is False
    assert source_map["notes"] == "Live checkpoint source map built from discovered sources."
    assert "Research Checkpoint: Costco" in checkpoint
    assert "Live checkpoint source map" in checkpoint
    assert "Mock mode produced" not in checkpoint
    assert "No live research" not in checkpoint


def test_live_checkpoint_includes_mocked_search_results_in_source_agent_prompt(
    tmp_path: Path,
) -> None:
    prompts_by_agent: dict[str, str] = {}
    search_client = WebSearchClient(
        provider=StaticSearchProvider(
            {
                "Costco official company primary source supplier meeting": [
                    SearchResult(
                        title="Costco supplier information",
                        publisher="Costco",
                        url="https://www.costco.com/suppliers.html",
                        snippet="Supplier expectations and information.",
                        publication_date="2026-01-10",
                    )
                ],
                "Costco recent news supplier meeting": [
                    SearchResult(
                        title="Recent Costco supplier coverage",
                        publisher="Mock News",
                        url="https://example.com/costco-supplier-news",
                        snippet="Recent reporting on Costco suppliers.",
                        publication_date="2026-04-01",
                    )
                ],
            }
        )
    )

    def fake_agent_runner(agent_key: str, agent: Any, prompt: str) -> Any:
        prompts_by_agent[agent_key] = prompt
        if agent_key == "intake":
            return ResearchCharter(
                target="Costco",
                target_type="company",
                research_lens="sales",
                depth="standard",
                deliverable="meeting_prep_brief",
                key_questions=["What should we understand before the supplier meeting?"],
            )
        if agent_key == "planner":
            return ResearchPlan(
                research_questions=["What does Costco expect from suppliers?"],
                report_sections=["overview", "supplier_context"],
                required_source_types=["primary_company", "news"],
                checkpoint_questions=["Which supplier category should be prioritized?"],
            )
        if agent_key == "source_discovery":
            assert "raw_search_results" in prompt
            assert "https://www.costco.com/suppliers.html" in prompt
            return SourceDiscoveryResult(
                sources=[
                    SourceCandidate(
                        id="src_costco_primary",
                        title="Costco supplier information",
                        publisher="Costco",
                        url="https://www.costco.com/suppliers.html",
                        source_type="primary_company",
                        publication_date="2026-01-10",
                        relevance_rationale="Primary source for supplier expectations.",
                        recommended_uses=["supplier context"],
                        bias_risk="high",
                    ),
                    SourceCandidate(
                        id="src_costco_news",
                        title="Recent Costco supplier coverage",
                        publisher="Mock News",
                        url="https://example.com/costco-supplier-news",
                        source_type="news",
                        publication_date="2026-04-01",
                        relevance_rationale="Recent context for meeting prep.",
                        recommended_uses=["recent developments"],
                        bias_risk="medium",
                    ),
                ]
            )
        raise AssertionError(f"Unexpected agent call: {agent_key}")

    result = run_research(
        "Research Costco before a supplier meeting",
        checkpoint_only=True,
        mock=False,
        runs_dir=tmp_path,
        agent_runner=fake_agent_runner,
        source_fetcher=_failing_source_fetcher,
        search_client=search_client,
    )

    run_dir = tmp_path / result.metadata.run_id
    sources = json.loads((run_dir / "sources.json").read_text())
    source_map = json.loads((run_dir / "source_map.json").read_text())

    assert "source_discovery" in prompts_by_agent
    assert sources[0]["url"] == "https://www.costco.com/suppliers.html"
    assert source_map["scores"][0]["source_id"] in {"src_costco_primary", "src_costco_news"}


def test_full_run_without_qa_writes_draft_only_from_mocked_synthesis_output(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    synthesis_prompt = ""

    def fake_agent_runner(agent_key: str, agent: Any, prompt: str) -> Any:
        nonlocal synthesis_prompt
        calls.append(agent_key)
        if agent_key == "intake":
            return ResearchCharter(
                target="ServiceTitan",
                target_type="company",
                research_lens="sales",
                depth="standard",
                deliverable="meeting_prep_brief",
                key_questions=["What should we understand before the sales meeting?"],
            )
        if agent_key == "planner":
            return ResearchPlan(
                research_questions=["What does ServiceTitan do?"],
                report_sections=["overview", "sales_context"],
                required_source_types=["primary_company", "news"],
                checkpoint_questions=["Which buyer persona matters most?"],
            )
        if agent_key == "source_discovery":
            return SourceDiscoveryResult(
                sources=[
                    SourceCandidate(
                        id="src_servicetitan_primary",
                        title="ServiceTitan company overview",
                        publisher="ServiceTitan",
                        url="https://www.servicetitan.com/company",
                        source_type="primary_company",
                        publication_date="2026-02-01",
                        relevance_rationale="Primary source for company description.",
                        recommended_uses=["overview"],
                        bias_risk="high",
                    )
                ]
            )
        if agent_key == "evidence_extraction":
            assert "approved_sources" in prompt
            assert "source_content" in prompt
            assert "Costco requires suppliers to meet delivery windows." in prompt
            assert "verbatim substring" in prompt
            return EvidenceExtractionResult(
                claims=[
                    EvidenceClaim(
                        id="claim_servicetitan_overview",
                        claim="ServiceTitan provides software for trades businesses.",
                        claim_type="fact",
                        source_id="src_servicetitan_primary",
                        source_title="ServiceTitan company overview",
                        source_url="https://www.servicetitan.com/company",
                        source_type="primary_company",
                        confidence="medium",
                        report_section="overview",
                        quote_or_excerpt="Costco requires suppliers to meet delivery windows.",
                    )
                ]
            )
        if agent_key in {"news", "competitor", "risk"}:
            return SpecialistAnalysis(
                specialist=agent_key,
                summary=f"{agent_key} analysis should stay source-bound.",
                source_ids=["src_servicetitan_primary"],
            )
        if agent_key == "synthesis":
            synthesis_prompt = prompt
            assert "research_plan" in prompt
            assert "source_map" in prompt
            assert "evidence_ledger" in prompt
            assert "specialist_analyses" in prompt
            assert "selected_report_template" in prompt
            assert "# Meeting Prep Brief" in prompt
            return Report(
                title="ServiceTitan Meeting Prep Brief",
                markdown=(
                    "# ServiceTitan Meeting Prep Brief\n\n"
                    "## Executive Summary\nEvidence-backed summary.\n\n"
                    "## Key Findings\n"
                    "- ServiceTitan provides software for trades businesses. "
                    "[claim_servicetitan_overview]\n\n"
                    "## Business Overview\nServiceTitan context.\n\n"
                    "## Competitors\nRelevant alternatives need follow-up.\n\n"
                    "## Risks\nPrimary-source bias.\n\n"
                    "## Open Questions\nWhich buyer persona matters most?\n\n"
                    "## Source Appendix\n- ServiceTitan company overview "
                    "(src_servicetitan_primary)\n"
                ),
                source_ids=["src_servicetitan_primary"],
            )
        raise AssertionError(f"Unexpected agent call: {agent_key}")

    result = run_research(
        "Research ServiceTitan before a sales meeting",
        checkpoint_only=False,
        full=True,
        mock=False,
        runs_dir=tmp_path,
        agent_runner=fake_agent_runner,
        source_fetcher=_fetcher_with_supplier_content,
        search_client=WebSearchClient(provider=StaticSearchProvider({})),
    )

    assert calls == [
        "intake",
        "planner",
        "source_discovery",
        "evidence_extraction",
        "news",
        "competitor",
        "risk",
        "synthesis",
    ]
    assert result.metadata.status == "draft_needs_qa"
    assert result.evidence_ledger is not None
    assert result.report is not None
    assert [analysis.specialist for analysis in result.specialist_analyses] == [
        "news",
        "competitor",
        "risk",
    ]
    assert result.evidence_ledger.claims[0].source_url == "https://www.servicetitan.com/company"
    assert "selected_report_template" in synthesis_prompt

    run_dir = tmp_path / result.metadata.run_id
    expected_files = {
        "metadata.json",
        "charter.json",
        "research_plan.json",
        "sources.json",
        "source_map.json",
        "source_content.json",
        "source_fetch_log.json",
        "specialist_analyses.json",
        "evidence_ledger.json",
        "draft_report.md",
        "checkpoint.md",
        "artifact_review.md",
        "run_log.jsonl",
    }
    evidence_ledger = json.loads((run_dir / "evidence_ledger.json").read_text())
    source_content = json.loads((run_dir / "source_content.json").read_text())
    source_fetch_log = json.loads((run_dir / "source_fetch_log.json").read_text())
    draft_report = (run_dir / "draft_report.md").read_text()
    artifact_review = (run_dir / "artifact_review.md").read_text()
    assert expected_files == {path.name for path in run_dir.iterdir() if path.is_file()}
    assert evidence_ledger["claims"][0]["id"] == "claim_servicetitan_overview"
    assert source_content[0]["source_id"] == "src_servicetitan_primary"
    assert "Costco requires suppliers to meet delivery windows." in source_content[0]["text"]
    assert source_fetch_log["results"][0]["status"] == "fetched"
    assert evidence_ledger["validation_warnings"] == []
    assert not (run_dir / "report.md").exists()
    assert "Final report published: no" in artifact_review
    assert "## Executive Summary" in draft_report
    assert "## Key Findings" in draft_report
    assert "## Business Overview" in draft_report
    assert "## Competitors" in draft_report
    assert "## Risks" in draft_report
    assert "## What We Do Not Know" in draft_report
    assert "## Source Appendix" in draft_report


def test_full_run_repairs_missing_meeting_unknowns_and_keeps_draft_nonfinal(
    tmp_path: Path,
) -> None:
    synthesis_prompt = ""

    def fake_agent_runner(agent_key: str, agent: Any, prompt: str) -> Any:
        nonlocal synthesis_prompt
        if agent_key == "intake":
            return ResearchCharter(
                target="Costco",
                target_type="company",
                research_lens="sales",
                depth="brief",
                deliverable="meeting_prep_brief",
                key_questions=["What matters before the supplier meeting?"],
            )
        if agent_key == "planner":
            return ResearchPlan(
                research_questions=["What should suppliers understand about Costco?"],
                report_sections=["overview", "supplier_context"],
                required_source_types=["primary_company", "news"],
                checkpoint_questions=["Which supplier category should be prioritized?"],
                data_gaps=["Supplier category not specified."],
            )
        if agent_key == "source_discovery":
            return SourceDiscoveryResult(
                sources=[
                    SourceCandidate(
                        id="src_costco_primary",
                        title="Costco supplier information",
                        publisher="Costco",
                        url="https://www.costco.com/suppliers.html",
                        source_type="primary_company",
                        publication_date="2026-01-10",
                        relevance_rationale="Primary source for supplier expectations.",
                        recommended_uses=["supplier context"],
                        bias_risk="high",
                    )
                ],
                gaps=["Missing source type: news"],
            )
        if agent_key == "evidence_extraction":
            return EvidenceExtractionResult(
                claims=[
                    EvidenceClaim(
                        id="claim_costco_supplier",
                        claim="Costco publishes supplier information for vendors.",
                        claim_type="fact",
                        source_id="src_costco_primary",
                        source_title="Costco supplier information",
                        source_url="https://www.costco.com/suppliers.html",
                        source_type="primary_company",
                        confidence="medium",
                        report_section="overview",
                    )
                ]
            )
        if agent_key in {"news", "competitor", "risk"}:
            return SpecialistAnalysis(
                specialist=agent_key,
                summary=f"{agent_key} analysis should stay source-bound.",
                source_ids=["src_costco_primary"],
            )
        if agent_key == "synthesis":
            synthesis_prompt = prompt
            return Report(
                title="Costco Supplier Meeting Brief",
                markdown=(
                    "# Costco Supplier Meeting Brief\n\n"
                    "## Executive Summary\nEvidence-backed summary.\n\n"
                    "## Key Findings\n"
                    "- Costco publishes supplier information for vendors. "
                    "[claim_costco_supplier]\n\n"
                    "## Business Overview\nCostco supplier context.\n\n"
                    "## Competitors\nRelevant alternatives need follow-up.\n\n"
                    "## Risks\nPrimary-source bias.\n\n"
                    "## Source Appendix\n- Costco supplier information (src_costco_primary)\n"
                ),
                source_ids=["src_costco_primary"],
            )
        raise AssertionError(f"Unexpected agent call: {agent_key}")

    result = run_research(
        "Research Costco before a supplier meeting",
        checkpoint_only=False,
        full=True,
        mock=False,
        runs_dir=tmp_path,
        agent_runner=fake_agent_runner,
        source_fetcher=_failing_source_fetcher,
        search_client=WebSearchClient(provider=StaticSearchProvider({})),
    )

    run_dir = tmp_path / result.metadata.run_id
    metadata = json.loads((run_dir / "metadata.json").read_text())
    draft_report = (run_dir / "draft_report.md").read_text()

    assert result.metadata.status == "draft_needs_qa"
    assert metadata["status"] == "draft_needs_qa"
    assert "What We Do Not Know is mandatory" in synthesis_prompt
    assert "## What We Do Not Know" in draft_report
    assert "Which supplier category should be prioritized?" in draft_report
    assert "Missing source type: news" in draft_report
    assert "Supplier category not specified." in draft_report
    assert not (run_dir / "report.md").exists()


def test_full_run_marks_report_with_unknown_source_reference_for_revision(
    tmp_path: Path,
) -> None:
    def fake_agent_runner(agent_key: str, agent: Any, prompt: str) -> Any:
        if agent_key == "intake":
            return ResearchCharter(
                target="ServiceTitan",
                target_type="company",
                research_lens="sales",
                depth="standard",
                deliverable="meeting_prep_brief",
                key_questions=["What should we understand before the sales meeting?"],
            )
        if agent_key == "planner":
            return ResearchPlan(
                research_questions=["What does ServiceTitan do?"],
                report_sections=["overview", "sales_context"],
                required_source_types=["primary_company"],
                checkpoint_questions=["Which buyer persona matters most?"],
            )
        if agent_key == "source_discovery":
            return SourceDiscoveryResult(
                sources=[
                    SourceCandidate(
                        id="src_servicetitan_primary",
                        title="ServiceTitan company overview",
                        publisher="ServiceTitan",
                        url="https://www.servicetitan.com/company",
                        source_type="primary_company",
                        publication_date="2026-02-01",
                        relevance_rationale="Primary source for company description.",
                        recommended_uses=["overview"],
                        bias_risk="high",
                    )
                ]
            )
        if agent_key in {"news", "competitor", "risk"}:
            return SpecialistAnalysis(
                specialist=agent_key,
                summary="Source-bound analysis.",
                source_ids=["src_servicetitan_primary"],
            )
        if agent_key == "evidence_extraction":
            return EvidenceExtractionResult(
                claims=[
                    EvidenceClaim(
                        id="claim_servicetitan_overview",
                        claim="ServiceTitan provides software for trades businesses.",
                        claim_type="fact",
                        source_id="src_servicetitan_primary",
                        source_title="ServiceTitan company overview",
                        source_url="https://www.servicetitan.com/company",
                        source_type="primary_company",
                        confidence="medium",
                        report_section="overview",
                    )
                ]
            )
        if agent_key == "synthesis":
            return Report(
                title="Bad Report",
                markdown=(
                    "# Bad Report\n\n"
                    "## Executive Summary\nSummary.\n\n"
                    "## Key Findings\nFinding.\n\n"
                    "## Business Overview\nOverview.\n\n"
                    "## Competitors\nCompetitors.\n\n"
                    "## Risks\nRisks.\n\n"
                    "## Open Questions\nQuestions.\n\n"
                    "## Source Appendix\nSources.\n"
                ),
                source_ids=["src_not_in_ledger_or_map"],
            )
        raise AssertionError(f"Unexpected agent call: {agent_key}")

    result = run_research(
        "Research ServiceTitan before a sales meeting",
        checkpoint_only=False,
        full=True,
        mock=False,
        runs_dir=tmp_path,
        agent_runner=fake_agent_runner,
        source_fetcher=_failing_source_fetcher,
        search_client=WebSearchClient(provider=StaticSearchProvider({})),
    )

    run_dir = tmp_path / result.metadata.run_id
    assert result.metadata.status == "draft_needs_revision"
    assert result.report is not None
    assert result.report.status == "draft_needs_revision"
    assert (run_dir / "draft_report.md").exists()
    assert not (run_dir / "report.md").exists()


def test_full_run_marks_report_with_unknown_claim_reference_for_revision(
    tmp_path: Path,
) -> None:
    def fake_agent_runner(agent_key: str, agent: Any, prompt: str) -> Any:
        if agent_key == "intake":
            return ResearchCharter(
                target="ServiceTitan",
                target_type="company",
                research_lens="sales",
                depth="standard",
                deliverable="meeting_prep_brief",
                key_questions=["What should we understand before the sales meeting?"],
            )
        if agent_key == "planner":
            return ResearchPlan(
                research_questions=["What does ServiceTitan do?"],
                report_sections=["overview", "sales_context"],
                required_source_types=["primary_company"],
                checkpoint_questions=["Which buyer persona matters most?"],
            )
        if agent_key == "source_discovery":
            return SourceDiscoveryResult(
                sources=[
                    SourceCandidate(
                        id="src_servicetitan_primary",
                        title="ServiceTitan company overview",
                        publisher="ServiceTitan",
                        url="https://www.servicetitan.com/company",
                        source_type="primary_company",
                        publication_date="2026-02-01",
                        relevance_rationale="Primary source for company description.",
                        recommended_uses=["overview"],
                        bias_risk="high",
                    )
                ]
            )
        if agent_key == "evidence_extraction":
            return EvidenceExtractionResult(
                claims=[
                    EvidenceClaim(
                        id="claim_servicetitan_overview",
                        claim="ServiceTitan provides software for trades businesses.",
                        claim_type="fact",
                        source_id="src_servicetitan_primary",
                        source_title="ServiceTitan company overview",
                        source_url="https://www.servicetitan.com/company",
                        source_type="primary_company",
                        confidence="medium",
                        report_section="overview",
                    )
                ]
            )
        if agent_key in {"news", "competitor", "risk"}:
            return SpecialistAnalysis(
                specialist=agent_key,
                summary="Source-bound analysis.",
                source_ids=["src_servicetitan_primary"],
            )
        if agent_key == "synthesis":
            return Report(
                title="Bad Report",
                markdown=(
                    "# Bad Report\n\n"
                    "## Executive Summary\nSummary.\n\n"
                    "## Key Findings\n"
                    "- Unsupported finding. [claim_not_in_ledger]\n\n"
                    "## Business Overview\nOverview.\n\n"
                    "## Competitors\nCompetitors.\n\n"
                    "## Risks\nRisks.\n\n"
                    "## Open Questions\nQuestions.\n\n"
                    "## Source Appendix\n- ServiceTitan company overview "
                    "(src_servicetitan_primary)\n"
                ),
                source_ids=["src_servicetitan_primary"],
            )
        raise AssertionError(f"Unexpected agent call: {agent_key}")

    result = run_research(
        "Research ServiceTitan before a sales meeting",
        checkpoint_only=False,
        full=True,
        mock=False,
        runs_dir=tmp_path,
        agent_runner=fake_agent_runner,
        source_fetcher=_failing_source_fetcher,
        search_client=WebSearchClient(provider=StaticSearchProvider({})),
    )

    run_dir = tmp_path / result.metadata.run_id
    assert result.metadata.status == "draft_needs_revision"
    assert result.report is not None
    assert result.report.status == "draft_needs_revision"
    assert (run_dir / "draft_report.md").exists()
    assert not (run_dir / "report.md").exists()


def test_synthesis_payload_uses_final_allowed_claim_ids_after_specialist_dedup(
    tmp_path: Path,
) -> None:
    synthesis_payload: dict[str, Any] = {}

    def fake_agent_runner(agent_key: str, agent: Any, prompt: str) -> Any:
        nonlocal synthesis_payload
        if agent_key == "intake":
            return ResearchCharter(
                target="Costco",
                target_type="company",
                research_lens="sales",
                depth="brief",
                deliverable="meeting_prep_brief",
                key_questions=["What matters before the supplier meeting?"],
            )
        if agent_key == "planner":
            return ResearchPlan(
                research_questions=["What should suppliers understand about Costco?"],
                report_sections=["overview", "supplier_context"],
                required_source_types=["primary_company"],
                checkpoint_questions=["Which supplier category should be prioritized?"],
            )
        if agent_key == "source_discovery":
            return SourceDiscoveryResult(
                sources=[
                    SourceCandidate(
                        id="src_costco_primary",
                        title="Costco supplier information",
                        publisher="Costco",
                        url="https://www.costco.com/suppliers.html",
                        source_type="primary_company",
                        publication_date="2026-01-10",
                        relevance_rationale="Primary source for supplier expectations.",
                        recommended_uses=["supplier context"],
                        bias_risk="high",
                    )
                ]
            )
        if agent_key == "evidence_extraction":
            return EvidenceExtractionResult(
                claims=[
                    EvidenceClaim(
                        id="c1",
                        claim="Costco requires suppliers to meet delivery windows.",
                        claim_type="fact",
                        source_id="src_costco_primary",
                        source_title="Costco supplier information",
                        source_url="https://www.costco.com/suppliers.html",
                        source_type="primary_company",
                        confidence="medium",
                        report_section="overview",
                    ),
                    EvidenceClaim(
                        id="c2",
                        claim="Costco requires suppliers to provide accurate item data.",
                        claim_type="fact",
                        source_id="src_costco_primary",
                        source_title="Costco supplier information",
                        source_url="https://www.costco.com/suppliers.html",
                        source_type="primary_company",
                        confidence="medium",
                        report_section="supplier_context",
                    ),
                ]
            )
        if agent_key == "news":
            return SpecialistAnalysis(
                specialist="news",
                summary="News analysis repeats final-ledger evidence.",
                evidence_claims=[
                    EvidenceClaim(
                        id="r1",
                        claim="Costco requires suppliers to meet delivery windows.",
                        claim_type="fact",
                        source_id="src_costco_primary",
                        source_title="Costco supplier information",
                        source_url="https://www.costco.com/suppliers.html",
                        source_type="primary_company",
                        confidence="medium",
                        report_section="overview",
                    )
                ],
                source_ids=["src_costco_primary"],
            )
        if agent_key in {"competitor", "risk"}:
            return SpecialistAnalysis(
                specialist=agent_key,
                summary="Source-bound analysis.",
                source_ids=["src_costco_primary"],
            )
        if agent_key == "synthesis":
            synthesis_payload = _json_payload_from_prompt(prompt)
            return Report(
                title="Costco Supplier Meeting Brief",
                markdown=(
                    "# Costco Supplier Meeting Brief\n\n"
                    "## Executive Summary\nEvidence-backed summary. [c1]\n\n"
                    "## Context for Meeting\nContext. [c1]\n\n"
                    "## What We Know\n"
                    "- Costco requires suppliers to meet delivery windows. [c1]\n"
                    "- Costco requires suppliers to provide accurate item data. [c2]\n\n"
                    "## What We Do Not Know\n- Category-specific requirements.\n\n"
                    "## Supplier/Buyer Angle\nCaveated angle. [c2]\n\n"
                    "## Questions to Ask\n- Which supplier category matters?\n\n"
                    "## Risks and Watchouts\n- Supplier requirements need validation. [c1]\n\n"
                    "## Evidence Limitations\n"
                    "- Evidence is thin: two claims from one source.\n\n"
                    "## Source Appendix\n- Costco supplier information "
                    "(src_costco_primary)\n"
                ),
                source_ids=["src_costco_primary"],
                claim_ids=["c1", "c2"],
            )
        raise AssertionError(f"Unexpected agent call: {agent_key}")

    result = run_research(
        "Research Costco before a supplier meeting",
        checkpoint_only=False,
        full=True,
        mock=False,
        runs_dir=tmp_path,
        agent_runner=fake_agent_runner,
        source_fetcher=_failing_source_fetcher,
        search_client=WebSearchClient(provider=StaticSearchProvider({})),
    )

    assert result.evidence_ledger is not None
    assert [claim.id for claim in result.evidence_ledger.claims] == ["c1", "c2"]
    assert synthesis_payload["allowed_claim_ids"] == ["c1", "c2"]
    assert "r1" not in synthesis_payload["allowed_claim_ids"]
    assert any(
        "Deduplicated near-duplicate evidence claim ID r1" in warning
        for warning in result.evidence_ledger.validation_warnings
    )
    assert "specialist_analyses" in synthesis_payload
    assert "r1" not in json.dumps(synthesis_payload["specialist_analyses"])
    assert "Do not cite claim IDs from specialist_analyses" in json.dumps(
        synthesis_payload["claim_reference_rules"]
    )
    assert "final evidence_ledger and allowed_claim_ids are authoritative" in json.dumps(
        synthesis_payload["claim_reference_rules"]
    )
    assert "skipped ID is not allowed" in json.dumps(
        synthesis_payload["claim_reference_rules"]
    )


def test_full_qa_run_with_stale_claim_id_fails_before_qa_and_writes_diagnostic(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def fake_agent_runner(agent_key: str, agent: Any, prompt: str) -> Any:
        calls.append(agent_key)
        if agent_key == "intake":
            return ResearchCharter(
                target="Costco",
                target_type="company",
                research_lens="sales",
                depth="brief",
                deliverable="meeting_prep_brief",
                key_questions=["What matters before the supplier meeting?"],
            )
        if agent_key == "planner":
            return ResearchPlan(
                research_questions=["What should suppliers understand about Costco?"],
                report_sections=["overview", "supplier_context"],
                required_source_types=["primary_company"],
                checkpoint_questions=["Which supplier category should be prioritized?"],
            )
        if agent_key == "source_discovery":
            return SourceDiscoveryResult(
                sources=[
                    SourceCandidate(
                        id="src_costco_primary",
                        title="Costco supplier information",
                        publisher="Costco",
                        url="https://www.costco.com/suppliers.html",
                        source_type="primary_company",
                        publication_date="2026-01-10",
                        relevance_rationale="Primary source for supplier expectations.",
                        recommended_uses=["supplier context"],
                        bias_risk="high",
                    )
                ]
            )
        if agent_key == "evidence_extraction":
            return EvidenceExtractionResult(
                claims=[
                    EvidenceClaim(
                        id="c1",
                        claim="Costco requires suppliers to meet delivery windows.",
                        claim_type="fact",
                        source_id="src_costco_primary",
                        source_title="Costco supplier information",
                        source_url="https://www.costco.com/suppliers.html",
                        source_type="primary_company",
                        confidence="medium",
                        report_section="overview",
                    ),
                    EvidenceClaim(
                        id="c2",
                        claim="Costco requires suppliers to provide accurate item data.",
                        claim_type="fact",
                        source_id="src_costco_primary",
                        source_title="Costco supplier information",
                        source_url="https://www.costco.com/suppliers.html",
                        source_type="primary_company",
                        confidence="medium",
                        report_section="supplier_context",
                    ),
                ]
            )
        if agent_key == "news":
            return SpecialistAnalysis(
                specialist="news",
                summary="News analysis repeats final-ledger evidence.",
                evidence_claims=[
                    EvidenceClaim(
                        id="r1",
                        claim="Costco requires suppliers to meet delivery windows.",
                        claim_type="fact",
                        source_id="src_costco_primary",
                        source_title="Costco supplier information",
                        source_url="https://www.costco.com/suppliers.html",
                        source_type="primary_company",
                        confidence="medium",
                        report_section="overview",
                    )
                ],
                source_ids=["src_costco_primary"],
            )
        if agent_key in {"competitor", "risk"}:
            return SpecialistAnalysis(
                specialist=agent_key,
                summary="Source-bound analysis.",
                source_ids=["src_costco_primary"],
            )
        if agent_key == "synthesis":
            return Report(
                title="Costco Supplier Meeting Brief",
                markdown=(
                    "# Costco Supplier Meeting Brief\n\n"
                    "## Executive Summary\nEvidence-backed summary. [r1]\n\n"
                    "## Context for Meeting\nContext. [c1]\n\n"
                    "## What We Know\n"
                    "- Costco requires suppliers to meet delivery windows. [r1]\n"
                    "- Costco requires suppliers to provide accurate item data. [c2]\n\n"
                    "## What We Do Not Know\n- Category-specific requirements.\n\n"
                    "## Supplier/Buyer Angle\nCaveated angle. [c2]\n\n"
                    "## Questions to Ask\n- Which supplier category matters?\n\n"
                    "## Risks and Watchouts\n- Supplier requirements need validation. [c1]\n\n"
                    "## Evidence Limitations\n"
                    "- Evidence is thin: two claims from one source.\n\n"
                    "## Source Appendix\n- Costco supplier information "
                    "(src_costco_primary)\n\n"
                    "Claim IDs cited: c1, c2, r1\n"
                ),
                source_ids=["src_costco_primary"],
            )
        if agent_key == "qa":
            raise AssertionError("QA should not run after pre-QA traceability failure.")
        raise AssertionError(f"Unexpected agent call: {agent_key}")

    result = run_research(
        "Research Costco before a supplier meeting",
        checkpoint_only=False,
        full=True,
        qa=True,
        mock=False,
        runs_dir=tmp_path,
        agent_runner=fake_agent_runner,
        source_fetcher=_failing_source_fetcher,
        search_client=WebSearchClient(provider=StaticSearchProvider({})),
    )

    run_dir = tmp_path / result.metadata.run_id
    assert calls == ["intake", "planner", "source_discovery", "evidence_extraction", "news", "competitor", "risk", "synthesis"]
    assert result.metadata.status == "draft_needs_revision"
    assert result.qa_review is None
    assert result.report is not None
    assert result.report.status == "draft_needs_revision"
    assert [claim.id for claim in result.evidence_ledger.claims] == ["c1", "c2"]
    assert (run_dir / "draft_report.md").exists()
    assert (run_dir / "report_revision.md").exists()
    assert not (run_dir / "qa_review.json").exists()
    assert not (run_dir / "report.md").exists()
    revision = (run_dir / "report_revision.md").read_text()
    assert "Report contains unknown evidence claim references: r1" in revision
    assert "QA was not run" in revision


def test_full_qa_run_with_allowed_claim_ids_reaches_qa_normally(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def fake_agent_runner(agent_key: str, agent: Any, prompt: str) -> Any:
        calls.append(agent_key)
        if agent_key == "intake":
            return ResearchCharter(
                target="Costco",
                target_type="company",
                research_lens="sales",
                depth="brief",
                deliverable="meeting_prep_brief",
                key_questions=["What matters before the supplier meeting?"],
            )
        if agent_key == "planner":
            return ResearchPlan(
                research_questions=["What should suppliers understand about Costco?"],
                report_sections=["overview", "supplier_context"],
                required_source_types=["primary_company"],
                checkpoint_questions=["Which supplier category should be prioritized?"],
            )
        if agent_key == "source_discovery":
            return SourceDiscoveryResult(
                sources=[
                    SourceCandidate(
                        id="src_costco_primary",
                        title="Costco supplier information",
                        publisher="Costco",
                        url="https://www.costco.com/suppliers.html",
                        source_type="primary_company",
                        publication_date="2026-01-10",
                        relevance_rationale="Primary source for supplier expectations.",
                        recommended_uses=["supplier context"],
                        bias_risk="high",
                    )
                ]
            )
        if agent_key == "evidence_extraction":
            return EvidenceExtractionResult(
                claims=[
                    EvidenceClaim(
                        id="c1",
                        claim="Costco requires suppliers to meet delivery windows.",
                        claim_type="fact",
                        source_id="src_costco_primary",
                        source_title="Costco supplier information",
                        source_url="https://www.costco.com/suppliers.html",
                        source_type="primary_company",
                        confidence="medium",
                        report_section="overview",
                    ),
                    EvidenceClaim(
                        id="c2",
                        claim="Costco requires suppliers to provide accurate item data.",
                        claim_type="fact",
                        source_id="src_costco_primary",
                        source_title="Costco supplier information",
                        source_url="https://www.costco.com/suppliers.html",
                        source_type="primary_company",
                        confidence="medium",
                        report_section="supplier_context",
                    ),
                ]
            )
        if agent_key in {"news", "competitor", "risk"}:
            return SpecialistAnalysis(
                specialist=agent_key,
                summary="Source-bound analysis.",
                source_ids=["src_costco_primary"],
            )
        if agent_key == "synthesis":
            return Report(
                title="Costco Supplier Meeting Brief",
                markdown=(
                    "# Costco Supplier Meeting Brief\n\n"
                    "## Executive Summary\nEvidence-backed summary. [c1]\n\n"
                    "## Context for Meeting\nContext. [c1]\n\n"
                    "## What We Know\n"
                    "- Costco requires suppliers to meet delivery windows. [c1]\n"
                    "- Costco requires suppliers to provide accurate item data. [c2]\n\n"
                    "## What We Do Not Know\n- Category-specific requirements.\n\n"
                    "## Supplier/Buyer Angle\nCaveated angle. [c2]\n\n"
                    "## Questions to Ask\n- Which supplier category matters?\n\n"
                    "## Risks and Watchouts\n- Supplier requirements need validation. [c1]\n\n"
                    "## Evidence Limitations\n"
                    "- Evidence is thin: two claims from one source.\n\n"
                    "## Source Appendix\n- Costco supplier information "
                    "(src_costco_primary)\n"
                ),
                source_ids=["src_costco_primary"],
                claim_ids=["c1", "c2"],
            )
        if agent_key == "qa":
            return QAReview(ready_to_publish=True, issues=[])
        raise AssertionError(f"Unexpected agent call: {agent_key}")

    result = run_research(
        "Research Costco before a supplier meeting",
        checkpoint_only=False,
        full=True,
        qa=True,
        mock=False,
        runs_dir=tmp_path,
        agent_runner=fake_agent_runner,
        source_fetcher=_failing_source_fetcher,
        search_client=WebSearchClient(provider=StaticSearchProvider({})),
    )

    run_dir = tmp_path / result.metadata.run_id
    assert calls[-1] == "qa"
    assert result.metadata.status == "report_ready"
    assert result.qa_review is not None
    assert result.qa_review.issues == []
    assert (run_dir / "qa_review.json").exists()
    assert (run_dir / "report.md").exists()
    assert not (run_dir / "report_revision.md").exists()


def test_full_run_marks_markdown_source_reference_not_in_source_map_for_revision(
    tmp_path: Path,
) -> None:
    def fake_agent_runner(agent_key: str, agent: Any, prompt: str) -> Any:
        if agent_key == "intake":
            return ResearchCharter(
                target="ServiceTitan",
                target_type="company",
                research_lens="sales",
                depth="standard",
                deliverable="meeting_prep_brief",
                key_questions=["What should we understand before the sales meeting?"],
            )
        if agent_key == "planner":
            return ResearchPlan(
                research_questions=["What does ServiceTitan do?"],
                report_sections=["overview", "sales_context"],
                required_source_types=["primary_company"],
                checkpoint_questions=["Which buyer persona matters most?"],
            )
        if agent_key == "source_discovery":
            return SourceDiscoveryResult(
                sources=[
                    SourceCandidate(
                        id="src_servicetitan_primary",
                        title="ServiceTitan company overview",
                        publisher="ServiceTitan",
                        url="https://www.servicetitan.com/company",
                        source_type="primary_company",
                        publication_date="2026-02-01",
                        relevance_rationale="Primary source for company description.",
                        recommended_uses=["overview"],
                        bias_risk="high",
                    )
                ]
            )
        if agent_key == "evidence_extraction":
            return EvidenceExtractionResult(
                claims=[
                    EvidenceClaim(
                        id="claim_servicetitan_overview",
                        claim="ServiceTitan provides software for trades businesses.",
                        claim_type="fact",
                        source_id="src_servicetitan_primary",
                        source_title="ServiceTitan company overview",
                        source_url="https://www.servicetitan.com/company",
                        source_type="primary_company",
                        confidence="medium",
                        report_section="overview",
                    )
                ]
            )
        if agent_key in {"news", "competitor", "risk"}:
            return SpecialistAnalysis(
                specialist=agent_key,
                summary="Source-bound analysis.",
                source_ids=["src_servicetitan_primary"],
            )
        if agent_key == "synthesis":
            return Report(
                title="Bad Report",
                markdown=(
                    "# Bad Report\n\n"
                    "## Executive Summary\nSummary. [claim_servicetitan_overview]\n\n"
                    "## Key Findings\nFinding.\n\n"
                    "## Business Overview\nOverview.\n\n"
                    "## Competitors\nCompetitors.\n\n"
                    "## Risks\nRisks.\n\n"
                    "## Open Questions\nQuestions.\n\n"
                    "## Source Appendix\n- Unknown source (src_not_in_source_map)\n"
                ),
                source_ids=["src_servicetitan_primary"],
            )
        raise AssertionError(f"Unexpected agent call: {agent_key}")

    result = run_research(
        "Research ServiceTitan before a sales meeting",
        checkpoint_only=False,
        full=True,
        mock=False,
        runs_dir=tmp_path,
        agent_runner=fake_agent_runner,
        source_fetcher=_failing_source_fetcher,
        search_client=WebSearchClient(provider=StaticSearchProvider({})),
    )

    run_dir = tmp_path / result.metadata.run_id
    assert result.metadata.status == "draft_needs_revision"
    assert result.report is not None
    assert result.report.status == "draft_needs_revision"
    assert (run_dir / "draft_report.md").exists()
    assert not (run_dir / "report.md").exists()


def test_specialist_claim_with_unknown_source_blocks_publication(tmp_path: Path) -> None:
    def fake_agent_runner(agent_key: str, agent: Any, prompt: str) -> Any:
        if agent_key == "intake":
            return ResearchCharter(
                target="ServiceTitan",
                target_type="company",
                research_lens="sales",
                depth="standard",
                deliverable="meeting_prep_brief",
                key_questions=["What should we understand before the sales meeting?"],
            )
        if agent_key == "planner":
            return ResearchPlan(
                research_questions=["What does ServiceTitan do?"],
                report_sections=["overview", "sales_context"],
                required_source_types=["primary_company"],
                checkpoint_questions=["Which buyer persona matters most?"],
            )
        if agent_key == "source_discovery":
            return SourceDiscoveryResult(
                sources=[
                    SourceCandidate(
                        id="src_servicetitan_primary",
                        title="ServiceTitan company overview",
                        publisher="ServiceTitan",
                        url="https://www.servicetitan.com/company",
                        source_type="primary_company",
                        publication_date="2026-02-01",
                        relevance_rationale="Primary source for company description.",
                        recommended_uses=["overview"],
                        bias_risk="high",
                    )
                ]
            )
        if agent_key == "evidence_extraction":
            return EvidenceExtractionResult(
                claims=[
                    EvidenceClaim(
                        id="claim_servicetitan_overview",
                        claim="ServiceTitan provides software for trades businesses.",
                        claim_type="fact",
                        source_id="src_servicetitan_primary",
                        source_title="ServiceTitan company overview",
                        source_url="https://www.servicetitan.com/company",
                        source_type="primary_company",
                        confidence="medium",
                        report_section="overview",
                    )
                ]
            )
        if agent_key == "news":
            assert "evidence_ledger" in prompt
            return SpecialistAnalysis(
                specialist="news",
                summary="Specialist claim should be validated through the ledger.",
                evidence_claims=[
                    EvidenceClaim(
                        id="claim_specialist_unknown_source",
                        claim="ServiceTitan had a recent unsupported development.",
                        claim_type="fact",
                        source_id="src_not_in_source_map",
                        source_url="https://example.com/unknown",
                        confidence="medium",
                        report_section="recent_developments",
                    )
                ],
                source_ids=["src_servicetitan_primary"],
            )
        if agent_key in {"competitor", "risk"}:
            return SpecialistAnalysis(
                specialist=agent_key,
                summary="Source-bound analysis.",
                source_ids=["src_servicetitan_primary"],
            )
        if agent_key == "synthesis":
            raise AssertionError("Synthesis should not run with invalid specialist evidence.")
        raise AssertionError(f"Unexpected agent call: {agent_key}")

    result = run_research(
        "Research ServiceTitan before a sales meeting",
        checkpoint_only=False,
        full=True,
        mock=False,
        runs_dir=tmp_path,
        agent_runner=fake_agent_runner,
        source_fetcher=_failing_source_fetcher,
        search_client=WebSearchClient(provider=StaticSearchProvider({})),
    )

    assert result.metadata.status == "evidence_needs_review"
    assert result.evidence_ledger is not None
    assert any(
        "claim_specialist_unknown_source" in warning and "unknown source id" in warning
        for warning in result.evidence_ledger.validation_warnings
    )

    run_dir = tmp_path / result.metadata.run_id
    expected_files = {
        "metadata.json",
        "charter.json",
        "research_plan.json",
        "sources.json",
        "source_map.json",
        "source_content.json",
        "source_fetch_log.json",
        "specialist_analyses.json",
        "evidence_ledger.json",
        "evidence_review.md",
        "checkpoint.md",
        "artifact_review.md",
        "run_log.jsonl",
    }
    assert expected_files == {path.name for path in run_dir.iterdir() if path.is_file()}
    assert not (run_dir / "draft_report.md").exists()
    assert not (run_dir / "report.md").exists()
    evidence_review = (run_dir / "evidence_review.md").read_text()
    assert "Synthesis and QA were not run" in evidence_review


def test_full_run_deduplicates_identical_claim_ids_before_synthesis(tmp_path: Path) -> None:
    calls: list[str] = []

    duplicate_claim = EvidenceClaim(
        id="claim_costco_supplier",
        claim="Costco publishes supplier information for vendors.",
        claim_type="fact",
        source_id="src_costco_primary",
        source_title="Costco supplier information",
        source_url="https://www.costco.com/suppliers.html",
        source_type="primary_company",
        confidence="medium",
        report_section="overview",
    )

    def fake_agent_runner(agent_key: str, agent: Any, prompt: str) -> Any:
        calls.append(agent_key)
        if agent_key == "intake":
            return ResearchCharter(
                target="Costco",
                target_type="company",
                research_lens="sales",
                depth="brief",
                deliverable="meeting_prep_brief",
                key_questions=["What matters before the supplier meeting?"],
            )
        if agent_key == "planner":
            return ResearchPlan(
                research_questions=["What should suppliers understand about Costco?"],
                report_sections=["overview", "supplier_context"],
                required_source_types=["primary_company"],
                checkpoint_questions=["Which supplier category should be prioritized?"],
            )
        if agent_key == "source_discovery":
            return SourceDiscoveryResult(
                sources=[
                    SourceCandidate(
                        id="src_costco_primary",
                        title="Costco supplier information",
                        publisher="Costco",
                        url="https://www.costco.com/suppliers.html",
                        source_type="primary_company",
                        publication_date="2026-01-10",
                        relevance_rationale="Primary source for supplier expectations.",
                        recommended_uses=["supplier context"],
                        bias_risk="high",
                    )
                ]
            )
        if agent_key == "evidence_extraction":
            return EvidenceExtractionResult(claims=[duplicate_claim, duplicate_claim])
        if agent_key in {"news", "competitor", "risk"}:
            return SpecialistAnalysis(
                specialist=agent_key,
                summary=f"{agent_key} analysis should stay source-bound.",
                source_ids=["src_costco_primary"],
            )
        if agent_key == "synthesis":
            assert "claim_costco_supplier" in prompt
            return Report(
                title="Costco Supplier Meeting Brief",
                markdown=(
                    "# Costco Supplier Meeting Brief\n\n"
                    "## Executive Summary\nEvidence-backed summary.\n\n"
                    "## Key Findings\n"
                    "- Costco publishes supplier information for vendors. "
                    "[claim_costco_supplier]\n\n"
                    "## Business Overview\nCostco supplier context.\n\n"
                    "## Competitors\nRelevant alternatives need follow-up.\n\n"
                    "## Risks\nPrimary-source bias.\n\n"
                    "## Open Questions\nWhich supplier category should be prioritized?\n\n"
                    "## Source Appendix\n- Costco supplier information (src_costco_primary)\n"
                ),
                source_ids=["src_costco_primary"],
            )
        raise AssertionError(f"Unexpected agent call: {agent_key}")

    result = run_research(
        "Research Costco before a supplier meeting",
        checkpoint_only=False,
        full=True,
        mock=False,
        runs_dir=tmp_path,
        agent_runner=fake_agent_runner,
        source_fetcher=_failing_source_fetcher,
        search_client=WebSearchClient(provider=StaticSearchProvider({})),
    )

    run_dir = tmp_path / result.metadata.run_id
    assert "synthesis" in calls
    assert result.metadata.status == "draft_needs_qa"
    assert result.evidence_ledger is not None
    assert [claim.id for claim in result.evidence_ledger.claims] == ["claim_costco_supplier"]
    assert any(
        "Deduplicated duplicate evidence claim ID claim_costco_supplier" in warning
        for warning in result.evidence_ledger.validation_warnings
    )
    assert (run_dir / "draft_report.md").exists()
    assert not (run_dir / "evidence_review.md").exists()
    assert not (run_dir / "report.md").exists()


def test_conflicting_base_duplicate_claim_ids_block_synthesis(tmp_path: Path) -> None:
    calls: list[str] = []

    def fake_agent_runner(agent_key: str, agent: Any, prompt: str) -> Any:
        calls.append(agent_key)
        if agent_key == "intake":
            return ResearchCharter(
                target="Costco",
                target_type="company",
                research_lens="sales",
                depth="brief",
                deliverable="meeting_prep_brief",
                key_questions=["What matters before the supplier meeting?"],
            )
        if agent_key == "planner":
            return ResearchPlan(
                research_questions=["What should suppliers understand about Costco?"],
                report_sections=["overview", "supplier_context"],
                required_source_types=["primary_company"],
                checkpoint_questions=["Which supplier category should be prioritized?"],
            )
        if agent_key == "source_discovery":
            return SourceDiscoveryResult(
                sources=[
                    SourceCandidate(
                        id="src_costco_primary",
                        title="Costco supplier information",
                        publisher="Costco",
                        url="https://www.costco.com/suppliers.html",
                        source_type="primary_company",
                        publication_date="2026-01-10",
                        relevance_rationale="Primary source for supplier expectations.",
                        recommended_uses=["supplier context"],
                        bias_risk="high",
                    )
                ]
            )
        if agent_key == "evidence_extraction":
            return EvidenceExtractionResult(
                claims=[
                    EvidenceClaim(
                        id="claim_conflict",
                        claim="Costco publishes supplier information for vendors.",
                        claim_type="fact",
                        source_id="src_costco_primary",
                        source_title="Costco supplier information",
                        source_url="https://www.costco.com/suppliers.html",
                        source_type="primary_company",
                        confidence="medium",
                        report_section="overview",
                    ),
                    EvidenceClaim(
                        id="claim_conflict",
                        claim="Costco has a durable supplier advantage.",
                        claim_type="inference",
                        source_id="src_costco_primary",
                        source_title="Costco supplier information",
                        source_url="https://www.costco.com/suppliers.html",
                        source_type="primary_company",
                        confidence="medium",
                        report_section="supplier_context",
                    ),
                ]
            )
        raise AssertionError(f"Unexpected agent call: {agent_key}")

    result = run_research(
        "Research Costco before a supplier meeting",
        checkpoint_only=False,
        full=True,
        qa=True,
        mock=False,
        runs_dir=tmp_path,
        agent_runner=fake_agent_runner,
        source_fetcher=_failing_source_fetcher,
        search_client=WebSearchClient(provider=StaticSearchProvider({})),
    )

    run_dir = tmp_path / result.metadata.run_id
    assert calls == ["intake", "planner", "source_discovery", "evidence_extraction"]
    assert result.metadata.status == "evidence_needs_review"
    assert result.evidence_ledger is not None
    assert [claim.id for claim in result.evidence_ledger.claims] == ["claim_conflict"]
    assert any(
        "Conflicting duplicate evidence claim ID claim_conflict" in warning
        for warning in result.evidence_ledger.validation_warnings
    )
    evidence_review = (run_dir / "evidence_review.md").read_text()
    assert "Conflicting duplicate evidence claim ID claim_conflict" in evidence_review
    assert not (run_dir / "draft_report.md").exists()
    assert not (run_dir / "qa_review.json").exists()
    assert not (run_dir / "report.md").exists()


def test_full_qa_run_renames_conflicting_specialist_duplicate_claim_ids(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def fake_agent_runner(agent_key: str, agent: Any, prompt: str) -> Any:
        calls.append(agent_key)
        if agent_key == "intake":
            return ResearchCharter(
                target="Costco",
                target_type="company",
                research_lens="sales",
                depth="brief",
                deliverable="meeting_prep_brief",
                key_questions=["What matters before the supplier meeting?"],
            )
        if agent_key == "planner":
            return ResearchPlan(
                research_questions=["What should suppliers understand about Costco?"],
                report_sections=["overview", "supplier_context"],
                required_source_types=["primary_company"],
                checkpoint_questions=["Which supplier category should be prioritized?"],
            )
        if agent_key == "source_discovery":
            return SourceDiscoveryResult(
                sources=[
                    SourceCandidate(
                        id="src_costco_primary",
                        title="Costco supplier information",
                        publisher="Costco",
                        url="https://www.costco.com/suppliers.html",
                        source_type="primary_company",
                        publication_date="2026-01-10",
                        relevance_rationale="Primary source for supplier expectations.",
                        recommended_uses=["supplier context"],
                        bias_risk="high",
                    )
                ]
            )
        if agent_key == "evidence_extraction":
            return EvidenceExtractionResult(
                claims=[
                    EvidenceClaim(
                        id="claim_costco_supplier",
                        claim="Costco publishes supplier information for vendors.",
                        claim_type="fact",
                        source_id="src_costco_primary",
                        source_title="Costco supplier information",
                        source_url="https://www.costco.com/suppliers.html",
                        source_type="primary_company",
                        confidence="medium",
                        report_section="overview",
                    )
                ]
            )
        if agent_key == "news":
            return SpecialistAnalysis(
                specialist="news",
                summary="News analysis uses source-bound context.",
                evidence_claims=[
                    EvidenceClaim(
                        id="claim_costco_supplier",
                        claim="Costco supplier context should be checked against recent news.",
                        claim_type="inference",
                        source_id="src_costco_primary",
                        source_title="Costco supplier information",
                        source_url="https://www.costco.com/suppliers.html",
                        source_type="primary_company",
                        confidence="medium",
                        report_section="supplier_context",
                    )
                ],
                source_ids=["src_costco_primary"],
            )
        if agent_key in {"competitor", "risk"}:
            return SpecialistAnalysis(
                specialist=agent_key,
                summary=f"{agent_key} analysis should stay source-bound.",
                source_ids=["src_costco_primary"],
            )
        if agent_key == "synthesis":
            assert "specialist_news_claim_costco_supplier" in prompt
            return Report(
                title="Costco Supplier Meeting Brief",
                markdown=(
                    "# Costco Supplier Meeting Brief\n\n"
                    "## Executive Summary\nEvidence-backed summary.\n\n"
                    "## Key Findings\n"
                    "- Costco publishes supplier information for vendors. "
                    "[claim_costco_supplier]\n\n"
                    "## Business Overview\nCostco supplier context.\n\n"
                    "## Competitors\nRelevant alternatives need follow-up.\n\n"
                    "## Risks\nPrimary-source bias.\n\n"
                    "## Open Questions\nWhich supplier category should be prioritized?\n\n"
                    "## Source Appendix\n- Costco supplier information (src_costco_primary)\n"
                ),
                source_ids=["src_costco_primary"],
            )
        if agent_key == "qa":
            return QAReview(ready_to_publish=True, issues=[])
        raise AssertionError(f"Unexpected agent call: {agent_key}")

    result = run_research(
        "Research Costco before a supplier meeting",
        checkpoint_only=False,
        full=True,
        qa=True,
        mock=False,
        runs_dir=tmp_path,
        agent_runner=fake_agent_runner,
        source_fetcher=_failing_source_fetcher,
        search_client=WebSearchClient(provider=StaticSearchProvider({})),
    )

    run_dir = tmp_path / result.metadata.run_id
    assert result.metadata.status == "report_ready"
    assert result.qa_review is not None
    assert result.evidence_ledger is not None
    claim_ids = [claim.id for claim in result.evidence_ledger.claims]
    assert claim_ids == [
        "claim_costco_supplier",
        "specialist_news_claim_costco_supplier",
    ]
    assert len(claim_ids) == len(set(claim_ids))
    assert any(
        "Renamed conflicting specialist evidence claim ID claim_costco_supplier "
        "to specialist_news_claim_costco_supplier" in warning
        for warning in result.evidence_ledger.validation_warnings
    )
    assert calls[-1] == "qa"
    assert (run_dir / "draft_report.md").exists()
    assert (run_dir / "qa_review.json").exists()
    assert (run_dir / "report.md").exists()
    assert (run_dir / "artifact_review.md").exists()
    assert not (run_dir / "evidence_review.md").exists()


def test_full_qa_run_saves_review_and_blocks_final_report_on_high_issue(tmp_path: Path) -> None:
    calls: list[str] = []
    qa_prompt = ""

    def fake_agent_runner(agent_key: str, agent: Any, prompt: str) -> Any:
        nonlocal qa_prompt
        calls.append(agent_key)
        if agent_key == "intake":
            return ResearchCharter(
                target="Salesforce",
                target_type="company",
                research_lens="investment",
                depth="standard",
                deliverable="investment_memo",
                key_questions=["What matters for investors?"],
            )
        if agent_key == "planner":
            return ResearchPlan(
                research_questions=["What does Salesforce do?"],
                report_sections=["overview", "risks"],
                required_source_types=["primary_company", "corporate_filing"],
                checkpoint_questions=["Which risks matter most?"],
            )
        if agent_key == "source_discovery":
            return SourceDiscoveryResult(
                sources=[
                    SourceCandidate(
                        id="src_salesforce_primary",
                        title="Salesforce company overview",
                        publisher="Salesforce",
                        url="https://www.salesforce.com/company/",
                        source_type="primary_company",
                        publication_date="2026-02-01",
                        relevance_rationale="Primary source for company description.",
                        recommended_uses=["overview"],
                        bias_risk="high",
                    )
                ]
            )
        if agent_key in {"financial", "industry", "competitor", "risk", "filings"}:
            return SpecialistAnalysis(
                specialist=agent_key,
                summary=f"{agent_key} analysis.",
                evidence_claims=[
                    EvidenceClaim(
                        id=f"claim_{agent_key}_specialist",
                        claim=f"{agent_key} specialist analysis is source-bound.",
                        claim_type="inference",
                        source_id="src_salesforce_primary",
                        source_title="Salesforce company overview",
                        source_url="https://www.salesforce.com/company/",
                        source_type="primary_company",
                        confidence="medium",
                        report_section="specialist_analysis",
                    )
                ],
                source_ids=["src_salesforce_primary"],
            )
        if agent_key == "evidence_extraction":
            return EvidenceExtractionResult(
                claims=[
                    EvidenceClaim(
                        id="claim_salesforce_overview",
                        claim="Salesforce provides customer relationship management software.",
                        claim_type="fact",
                        source_id="src_salesforce_primary",
                        source_title="Salesforce company overview",
                        source_url="https://www.salesforce.com/company/",
                        source_type="primary_company",
                        confidence="medium",
                        report_section="overview",
                    )
                ]
            )
        if agent_key == "synthesis":
            return Report(
                title="Salesforce Investment Memo",
                markdown=(
                    "# Salesforce Investment Memo\n\n"
                    "## Executive Summary\nEvidence-backed summary.\n\n"
                    "## Key Findings\n"
                    "- Salesforce provides customer relationship management software. "
                    "[claim_salesforce_overview]\n\n"
                    "## Business Overview\nSalesforce context.\n\n"
                    "## Competitors\nRelevant alternatives need follow-up.\n\n"
                    "## Risks\nPrimary-source bias.\n\n"
                    "## Open Questions\nWhich risks matter most?\n\n"
                    "## Source Appendix\n- Salesforce company overview "
                    "(src_salesforce_primary)\n"
                ),
                source_ids=["src_salesforce_primary"],
            )
        if agent_key == "qa":
            qa_prompt = prompt
            assert "research_charter" in prompt
            assert "source_map" in prompt
            assert "evidence_ledger" in prompt
            assert "draft_report" in prompt
            return QAReview(
                ready_to_publish=False,
                issues=[
                    QAIssue(
                        severity="high",
                        problem="Report overstates evidence from one primary source.",
                        suggested_fix="Add independent sources before publishing.",
                        affected_section="Key Findings",
                    )
                ],
            )
        raise AssertionError(f"Unexpected agent call: {agent_key}")

    result = run_research(
        "Research Salesforce for an investment memo",
        checkpoint_only=False,
        full=True,
        qa=True,
        mock=False,
        runs_dir=tmp_path,
        agent_runner=fake_agent_runner,
        source_fetcher=_failing_source_fetcher,
        search_client=WebSearchClient(provider=StaticSearchProvider({})),
    )

    assert calls == [
        "intake",
        "planner",
        "source_discovery",
        "evidence_extraction",
        "financial",
        "industry",
        "competitor",
        "risk",
        "filings",
        "synthesis",
        "qa",
    ]
    assert "draft_report" in qa_prompt
    assert result.metadata.status == "needs_review"
    assert result.qa_review is not None
    assert result.qa_review.issues[0].severity == "high"
    assert result.evidence_ledger is not None
    assert any(
        claim.id == "claim_financial_specialist"
        for claim in result.evidence_ledger.claims
    )

    run_dir = tmp_path / result.metadata.run_id
    expected_files = {
        "metadata.json",
        "charter.json",
        "research_plan.json",
        "sources.json",
        "source_map.json",
        "source_content.json",
        "source_fetch_log.json",
        "specialist_analyses.json",
        "evidence_ledger.json",
        "draft_report.md",
        "qa_review.json",
        "checkpoint.md",
        "artifact_review.md",
        "run_log.jsonl",
    }
    assert expected_files == {path.name for path in run_dir.iterdir() if path.is_file()}
    assert (run_dir / "draft_report.md").exists()
    assert not (run_dir / "report.md").exists()
    artifact_review = (run_dir / "artifact_review.md").read_text()
    assert "Final report published: no" in artifact_review
    assert "Fix high-severity QA blockers" in artifact_review
    qa_review = json.loads((run_dir / "qa_review.json").read_text())
    assert qa_review["issues"][0]["severity"] == "high"


def test_full_qa_run_repairs_missing_meeting_unknowns_and_writes_final_when_qa_passes(
    tmp_path: Path,
) -> None:
    def fake_agent_runner(agent_key: str, agent: Any, prompt: str) -> Any:
        if agent_key == "intake":
            return ResearchCharter(
                target="Costco",
                target_type="company",
                research_lens="sales",
                depth="brief",
                deliverable="meeting_prep_brief",
                key_questions=["What matters before the supplier meeting?"],
            )
        if agent_key == "planner":
            return ResearchPlan(
                research_questions=["What should suppliers understand about Costco?"],
                report_sections=["overview", "supplier_context"],
                required_source_types=["primary_company"],
                checkpoint_questions=["Which supplier category should be prioritized?"],
                data_gaps=["Supplier category not specified."],
            )
        if agent_key == "source_discovery":
            return SourceDiscoveryResult(
                sources=[
                    SourceCandidate(
                        id="src_costco_primary",
                        title="Costco supplier information",
                        publisher="Costco",
                        url="https://www.costco.com/suppliers.html",
                        source_type="primary_company",
                        publication_date="2026-01-10",
                        relevance_rationale="Primary source for supplier expectations.",
                        recommended_uses=["supplier context"],
                        bias_risk="high",
                    )
                ]
            )
        if agent_key == "evidence_extraction":
            return EvidenceExtractionResult(
                claims=[
                    EvidenceClaim(
                        id="claim_costco_supplier",
                        claim="Costco publishes supplier information for vendors.",
                        claim_type="fact",
                        source_id="src_costco_primary",
                        source_title="Costco supplier information",
                        source_url="https://www.costco.com/suppliers.html",
                        source_type="primary_company",
                        confidence="medium",
                        report_section="overview",
                    )
                ]
            )
        if agent_key in {"news", "competitor", "risk"}:
            return SpecialistAnalysis(
                specialist=agent_key,
                summary=f"{agent_key} analysis should stay source-bound.",
                source_ids=["src_costco_primary"],
            )
        if agent_key == "synthesis":
            return Report(
                title="Costco Supplier Meeting Brief",
                markdown=(
                    "# Costco Supplier Meeting Brief\n\n"
                    "## Executive Summary\nEvidence-backed summary.\n\n"
                    "## Key Findings\n"
                    "- Costco publishes supplier information for vendors. "
                    "[claim_costco_supplier]\n\n"
                    "## Business Overview\nCostco supplier context.\n\n"
                    "## Competitors\nRelevant alternatives need follow-up.\n\n"
                    "## Risks\nPrimary-source bias.\n\n"
                    "## Source Appendix\n- Costco supplier information (src_costco_primary)\n"
                ),
                source_ids=["src_costco_primary"],
            )
        if agent_key == "qa":
            return QAReview(ready_to_publish=True, issues=[])
        raise AssertionError(f"Unexpected agent call: {agent_key}")

    result = run_research(
        "Research Costco before a supplier meeting",
        checkpoint_only=False,
        full=True,
        qa=True,
        mock=False,
        runs_dir=tmp_path,
        agent_runner=fake_agent_runner,
        source_fetcher=_failing_source_fetcher,
        search_client=WebSearchClient(provider=StaticSearchProvider({})),
    )

    run_dir = tmp_path / result.metadata.run_id
    final_report = (run_dir / "report.md").read_text()

    assert result.metadata.status == "report_ready"
    assert result.qa_review is not None
    assert result.qa_review.issues == []
    assert "## What We Do Not Know" in final_report
    assert "Which supplier category should be prioritized?" in final_report
    assert "Supplier category not specified." in final_report
    assert (run_dir / "draft_report.md").exists()
    artifact_review = (run_dir / "artifact_review.md").read_text()
    assert "Final report published: yes" in artifact_review
