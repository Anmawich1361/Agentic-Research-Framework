from typing import Any

from agentic_research.models import ResearchCharter, ResearchPlan
from agentic_research.tools.web_search import (
    SearchResult,
    StaticSearchProvider,
    WebSearchClient,
    build_source_search_queries,
    create_web_search_tool,
)


class PartiallyFailingSearchProvider:
    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        if "primary source" in query:
            raise TimeoutError("search timed out")
        return [
            SearchResult(
                title="Recent Costco supplier coverage",
                publisher="Mock News",
                url="https://example.com/costco-supplier-news",
                snippet="Recent reporting on Costco suppliers.",
                publication_date="2026-04-01",
            )
        ][:max_results]


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


def _investment_charter() -> ResearchCharter:
    return ResearchCharter(
        target="ATS Corporation",
        target_type="company",
        research_lens="investment",
        depth="standard",
        deliverable="investment_meeting_brief",
        key_questions=["Should we invest after the latest earnings release?"],
    )


def _investment_plan() -> ResearchPlan:
    return ResearchPlan(
        research_questions=["What changed in the most recent quarterly results?"],
        report_sections=["overview", "latest_results", "valuation", "peers"],
        required_source_types=[
            "Management discussion & analysis (MD&A) and earnings release/transcript",
            "market data / valuation screens / trading history",
            "peer company source set",
            "industry primer",
        ],
        checkpoint_questions=["Which valuation lens should be prioritized?"],
    )


def test_build_source_search_queries_targets_required_source_types() -> None:
    queries = build_source_search_queries(_charter(), _plan())

    assert "Costco SEC 10-K annual report site:sec.gov" in queries
    assert "Costco SEC 6-K earnings results site:sec.gov" in queries
    assert "Costco official company source" in queries
    assert "Costco investor relations financial results" in queries
    assert "Costco investor relations investor presentation" in queries
    assert "Costco earnings release" in queries
    assert "Costco quarterly results" in queries
    assert "Costco latest results press release" in queries
    assert "Costco earnings transcript" in queries
    assert "Costco official company primary source" in queries
    assert "Costco recent news" in queries


def test_build_source_search_queries_prefers_accessible_sec_filings_for_company() -> None:
    queries = build_source_search_queries(_charter(), _plan())

    assert queries[0].startswith("Costco SEC 10-K annual report")
    assert "site:sec.gov" in queries[0]


def test_build_source_search_queries_uses_simple_date_aware_investment_queries() -> None:
    queries = build_source_search_queries(
        _investment_charter(),
        _investment_plan(),
        feedback_text="Earnings were just reported May 28 2026.",
    )

    assert "ATS Corporation earnings release" in queries
    assert "ATS Corporation quarterly results" in queries
    assert "ATS Corporation investor relations financial results" in queries
    assert "ATS Corporation latest results press release" in queries
    assert "ATS Corporation May 28 2026 earnings release" in queries
    assert "ATS Corporation May 28 2026 quarterly results" in queries
    assert "ATS Corporation market data valuation" in queries
    assert "ATS Corporation peers competitors valuation" in queries
    assert "ATS Corporation industry primer" in queries
    assert not any("Management discussion" in query for query in queries)


def test_web_search_client_dedupes_mocked_search_results(mocker: Any) -> None:
    mocker.patch(
        "agentic_research.tools.web_search._sec_filing_fallback_results",
        return_value=[],
    )
    provider = StaticSearchProvider(
        {
            "Costco official company primary source": [
                SearchResult(
                    title="Costco supplier information",
                    publisher="Costco",
                    url="https://www.costco.com/suppliers.html",
                    snippet="Supplier expectations and information.",
                    publication_date="2026-01-10",
                ),
            ],
            "Costco recent news": [
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


class _FailingThenWorkingProvider:
    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        if "SEC" in query:
            raise TimeoutError("search timeout")
        return [
            SearchResult(
                title="Recent Costco supplier coverage",
                publisher="Mock News",
                url="https://example.com/costco-supplier-news",
                snippet="Recent reporting on Costco suppliers.",
            )
        ][:max_results]


def test_web_search_client_continues_after_individual_query_failure(mocker: Any) -> None:
    mocker.patch(
        "agentic_research.tools.web_search._sec_filing_fallback_results",
        return_value=[],
    )
    client = WebSearchClient(provider=_FailingThenWorkingProvider())

    results = client.search_many(build_source_search_queries(_charter(), _plan()))

    assert [result.url for result in results] == [
        "https://example.com/costco-supplier-news"
    ]


def test_web_search_client_records_query_failure_diagnostics(mocker: Any) -> None:
    mocker.patch(
        "agentic_research.tools.web_search._sec_filing_fallback_results",
        return_value=[],
    )
    client = WebSearchClient(provider=_FailingThenWorkingProvider())

    client.search_many(build_source_search_queries(_charter(), _plan()))

    assert len(client.last_failures) == 2
    assert client.last_failures[0].query == (
        "Costco SEC 10-K annual report site:sec.gov"
    )
    assert client.last_failures[0].error_type == "TimeoutError"
    assert client.last_failures[0].error == "search timeout"


class _AlwaysFailingProvider:
    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        raise TimeoutError("search timeout")


def test_web_search_client_uses_sec_filing_fallback_for_sec_queries(mocker: Any) -> None:
    fallback = SearchResult(
        title="COSTCO WHOLESALE CORP /NEW latest Form 10-K",
        publisher="U.S. Securities and Exchange Commission",
        url="https://www.sec.gov/Archives/edgar/data/909832/000090983225000101/cost-20250831.htm",
        snippet="Direct SEC Form 10-K filing URL for COSTCO WHOLESALE CORP /NEW.",
    )
    mocker.patch(
        "agentic_research.tools.web_search._sec_filing_fallback_results",
        return_value=[fallback],
    )
    client = WebSearchClient(provider=_AlwaysFailingProvider())

    results = client.search("Costco SEC 10-K annual report site:sec.gov supplier meeting")

    assert results == [fallback]


def test_web_search_client_uses_recent_sec_filing_fallback_for_6k_earnings_exhibit(
    mocker: Any,
) -> None:
    def fake_sec_json_get(url: str, *, timeout_seconds: float = 10) -> Any:
        del timeout_seconds
        if url.endswith("/company_tickers.json"):
            return {
                "0": {
                    "cik_str": 1394832,
                    "ticker": "ATS",
                    "title": "ATS CORP",
                }
            }
        if url.endswith("/CIK0001394832.json"):
            return {
                "filings": {
                    "recent": {
                        "form": ["6-K", "10-K"],
                        "accessionNumber": [
                            "0001394832-26-000017",
                            "0001394832-25-000010",
                        ],
                        "primaryDocument": ["ats-6k.htm", "ats-20250331.htm"],
                    }
                }
            }
        if url.endswith("/000139483226000017/index.json"):
            return {
                "directory": {
                    "item": [
                        {"name": "ats-6k.htm"},
                        {"name": "ats-pressreleasexfy26q4.htm"},
                    ]
                }
            }
        raise AssertionError(f"Unexpected SEC JSON URL: {url}")

    mocker.patch("agentic_research.tools.web_search._sec_json_get", fake_sec_json_get)
    client = WebSearchClient(provider=StaticSearchProvider({}))

    results = client.search("ATS Corporation SEC 6-K earnings results site:sec.gov")

    assert [result.url for result in results] == [
        "https://www.sec.gov/Archives/edgar/data/1394832/"
        "000139483226000017/ats-pressreleasexfy26q4.htm"
    ]
    assert results[0].publisher == "U.S. Securities and Exchange Commission"
    assert "Form 6-K" in results[0].title


def test_web_search_client_adds_sec_fallback_even_when_provider_returns_results(
    mocker: Any,
) -> None:
    fallback = SearchResult(
        title="ATS Corp /ATS latest Form 6-K",
        publisher="U.S. Securities and Exchange Commission",
        url=(
            "https://www.sec.gov/Archives/edgar/data/1394832/"
            "000139483226000017/ats-pressreleasexfy26q4.htm"
        ),
        snippet="Direct SEC Form 6-K filing URL for ATS Corp /ATS.",
    )
    provider_result = SearchResult(
        title="ATS Corp /ATS latest Form 6-K",
        publisher="U.S. Securities and Exchange Commission",
        url=(
            "https://www.sec.gov/Archives/edgar/data/1394832/"
            "000162828026008830/a2026-2x17xraymondjamesins.htm"
        ),
        snippet="Direct SEC Form 6-K filing URL for ATS Corp /ATS.",
    )
    mocker.patch(
        "agentic_research.tools.web_search._sec_filing_fallback_results",
        return_value=[fallback],
    )
    client = WebSearchClient(
        provider=StaticSearchProvider(
            {
                "ATS Corporation SEC 6-K earnings results site:sec.gov": [
                    provider_result
                ]
            }
        )
    )

    results = client.search("ATS Corporation SEC 6-K earnings results site:sec.gov")

    assert [result.url for result in results] == [
        fallback.url,
        provider_result.url,
    ]


def test_create_web_search_tool_is_agent_compatible() -> None:
    tool = create_web_search_tool(WebSearchClient(provider=StaticSearchProvider({})))

    assert tool.name == "web_search"
