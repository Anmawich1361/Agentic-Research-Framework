import json
from pathlib import Path
from typing import Any

from agentic_research.models import (
    EvidenceClaim,
    EvidenceExtractionResult,
    ResearchCharter,
    ResearchPlan,
    SourceCandidate,
    SourceDiscoveryResult,
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


def test_full_run_extracts_evidence_and_writes_ledger(tmp_path: Path) -> None:
    calls: list[str] = []

    def fake_agent_runner(agent_key: str, agent: Any, prompt: str) -> Any:
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

    assert calls == ["intake", "planner", "source_discovery", "evidence_extraction"]
    assert result.metadata.status == "evidence_ready"
    assert result.evidence_ledger is not None
    assert result.evidence_ledger.claims[0].source_url == "https://www.servicetitan.com/company"

    run_dir = tmp_path / result.metadata.run_id
    evidence_ledger = json.loads((run_dir / "evidence_ledger.json").read_text())
    assert evidence_ledger["claims"][0]["id"] == "claim_servicetitan_overview"
    assert evidence_ledger["validation_warnings"] == []
