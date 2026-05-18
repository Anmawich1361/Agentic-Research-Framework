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
    SourceCandidate,
    SourceDiscoveryResult,
    SpecialistAnalysis,
)
from agentic_research.orchestrator import run_research
from agentic_research.tools.web_search import SearchResult, StaticSearchProvider, WebSearchClient


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
    assert metadata["mock"] is False
    assert "Research Checkpoint: Costco" in checkpoint


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
        search_client=search_client,
    )

    run_dir = tmp_path / result.metadata.run_id
    sources = json.loads((run_dir / "sources.json").read_text())
    source_map = json.loads((run_dir / "source_map.json").read_text())

    assert "source_discovery" in prompts_by_agent
    assert sources[0]["url"] == "https://www.costco.com/suppliers.html"
    assert source_map["scores"][0]["source_id"] in {"src_costco_primary", "src_costco_news"}


def test_full_run_generates_report_from_mocked_synthesis_output(tmp_path: Path) -> None:
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
        search_client=WebSearchClient(provider=StaticSearchProvider({})),
    )

    assert calls == [
        "intake",
        "planner",
        "source_discovery",
        "news",
        "competitor",
        "risk",
        "evidence_extraction",
        "synthesis",
    ]
    assert result.metadata.status == "report_ready"
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
    evidence_ledger = json.loads((run_dir / "evidence_ledger.json").read_text())
    draft_report = (run_dir / "draft_report.md").read_text()
    final_report = (run_dir / "report.md").read_text()
    assert evidence_ledger["claims"][0]["id"] == "claim_servicetitan_overview"
    assert evidence_ledger["validation_warnings"] == []
    assert draft_report == final_report
    assert "## Executive Summary" in final_report
    assert "## Key Findings" in final_report
    assert "## Business Overview" in final_report
    assert "## Competitors" in final_report
    assert "## Risks" in final_report
    assert "## Open Questions" in final_report
    assert "## Source Appendix" in final_report


def test_full_run_rejects_report_with_unknown_source_reference(tmp_path: Path) -> None:
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

    try:
        run_research(
            "Research ServiceTitan before a sales meeting",
            checkpoint_only=False,
            full=True,
            mock=False,
            runs_dir=tmp_path,
            agent_runner=fake_agent_runner,
            search_client=WebSearchClient(provider=StaticSearchProvider({})),
        )
    except ValueError as exc:
        assert "unknown source references" in str(exc)
    else:
        raise AssertionError("Expected unknown source references to fail report generation")


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
        search_client=WebSearchClient(provider=StaticSearchProvider({})),
    )

    assert calls == [
        "intake",
        "planner",
        "source_discovery",
        "financial",
        "industry",
        "competitor",
        "risk",
        "filings",
        "evidence_extraction",
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
    assert (run_dir / "draft_report.md").exists()
    assert not (run_dir / "report.md").exists()
    qa_review = json.loads((run_dir / "qa_review.json").read_text())
    assert qa_review["issues"][0]["severity"] == "high"
