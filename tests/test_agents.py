from agentic_research.agents import (
    create_agent_set,
    create_research_agent,
    get_agent_output_type,
)
from agentic_research.models import (
    EvidenceExtractionResult,
    QAReview,
    ResearchCharter,
    ResearchPlan,
    Report,
    SourceDiscoveryResult,
    SpecialistAnalysis,
)
from agentic_research.tools.web_search import StaticSearchProvider, WebSearchClient


def test_agent_factory_loads_prompts_and_structured_outputs() -> None:
    intake = create_research_agent("intake")

    assert intake.name == "Intake Agent"
    assert isinstance(intake.instructions, str)
    assert "structured research charter" in intake.instructions
    assert get_agent_output_type("intake") is ResearchCharter
    assert get_agent_output_type("planner") is ResearchPlan
    assert get_agent_output_type("source_discovery") is SourceDiscoveryResult
    assert get_agent_output_type("evidence_extraction") is EvidenceExtractionResult
    assert get_agent_output_type("synthesis") is Report
    assert get_agent_output_type("qa") is QAReview
    assert get_agent_output_type("industry") is SpecialistAnalysis
    assert get_agent_output_type("competitor") is SpecialistAnalysis
    assert get_agent_output_type("news") is SpecialistAnalysis
    assert get_agent_output_type("risk") is SpecialistAnalysis
    assert get_agent_output_type("financial") is SpecialistAnalysis
    assert get_agent_output_type("filings") is SpecialistAnalysis


def test_agent_set_creates_required_phase_2_agents() -> None:
    agent_set = create_agent_set()

    assert agent_set.intake.name == "Intake Agent"
    assert agent_set.planner.name == "Research Planner Agent"
    assert agent_set.source_discovery.name == "Source Discovery Agent"
    assert agent_set.evidence_extraction.name == "Evidence Extraction Agent"
    assert agent_set.synthesis.name == "Synthesis Agent"
    assert agent_set.qa.name == "QA Agent"
    assert agent_set.industry.name == "Industry Agent"
    assert agent_set.competitor.name == "Competitor Agent"
    assert agent_set.news.name == "News Agent"
    assert agent_set.risk.name == "Risk Agent"
    assert agent_set.financial.name == "Financial Agent"
    assert agent_set.filings.name == "Filings Agent"


def test_source_discovery_agent_receives_web_search_tool() -> None:
    search_client = WebSearchClient(provider=StaticSearchProvider({}))
    agent = create_research_agent("source_discovery", search_client=search_client)

    assert [tool.name for tool in agent.tools] == ["web_search"]
