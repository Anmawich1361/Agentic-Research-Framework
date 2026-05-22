from agentic_research.models import ResearchCharter, ResearchPlan
from agentic_research.tools.web_search import (
    SearchResult,
    StaticSearchProvider,
    WebSearchClient,
    build_source_search_queries,
    create_web_search_tool,
)


def _charter() -> ResearchCharter:
    return ResearchCharter(
        target="Costco",
        target_type="company",
        research_lens="sales",
        depth="standard",
        deliverable="meeting_prep_brief",
        key_questions=["What should we understand before a supplier meeting?"],
    )


def _plan() -> ResearchPlan:
    return ResearchPlan(
        research_questions=["What does Costco expect from suppliers?"],
        report_sections=["overview", "supplier_context"],
        required_source_types=["primary_company", "news"],
        checkpoint_questions=["Which supplier category should be prioritized?"],
    )


def test_build_source_search_queries_targets_required_source_types() -> None:
    queries = build_source_search_queries(_charter(), _plan())

    assert queries == [
        "Costco SEC 10-K annual report site:sec.gov supplier meeting",
        "Costco official company primary source supplier meeting",
        "Costco recent news supplier meeting",
    ]


def test_build_source_search_queries_prefers_accessible_sec_filings_for_company() -> None:
    queries = build_source_search_queries(_charter(), _plan())

    assert queries[0].startswith("Costco SEC 10-K annual report")
    assert "site:sec.gov" in queries[0]


def test_web_search_client_dedupes_mocked_search_results() -> None:
    provider = StaticSearchProvider(
        {
            "Costco official company primary source supplier meeting": [
                SearchResult(
                    title="Costco supplier information",
                    publisher="Costco",
                    url="https://www.costco.com/suppliers.html",
                    snippet="Supplier expectations and information.",
                    publication_date="2026-01-10",
                ),
            ],
            "Costco recent news supplier meeting": [
                SearchResult(
                    title="Costco supplier information",
                    publisher="Costco",
                    url="https://www.costco.com/suppliers.html",
                    snippet="Duplicate result.",
                ),
                SearchResult(
                    title="Recent Costco supplier coverage",
                    publisher="Mock News",
                    url="https://example.com/costco-supplier-news",
                    snippet="Recent reporting on Costco suppliers.",
                    publication_date="2026-04-01",
                ),
            ],
        }
    )
    client = WebSearchClient(provider=provider)

    results = client.search_many(build_source_search_queries(_charter(), _plan()))

    assert [result.url for result in results] == [
        "https://www.costco.com/suppliers.html",
        "https://example.com/costco-supplier-news",
    ]


def test_create_web_search_tool_is_agent_compatible() -> None:
    tool = create_web_search_tool(WebSearchClient(provider=StaticSearchProvider({})))

    assert tool.name == "web_search"
