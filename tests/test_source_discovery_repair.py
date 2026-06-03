import json
from pathlib import Path

from agentic_research.models import (
    ResearchCharter,
    ResearchPlan,
    SourceCandidate,
    SourceFetchLog,
    SourceFetchResult,
    SourceMap,
    SourceScore,
    UserFeedback,
)
from agentic_research.source_discovery_repair import (
    build_source_discovery_review,
    investment_source_coverage_gaps,
    repair_source_map_from_feedback,
)
from agentic_research.tools.web_search import SearchResult, WebSearchClient


class _AtsRepairSearchProvider:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        self.queries.append(query)
        if "earnings release" in query.lower():
            return [
                SearchResult(
                    title="ATS Reports Fourth Quarter Fiscal 2026 Results",
                    publisher="U.S. Securities and Exchange Commission",
                    url=(
                        "https://www.sec.gov/Archives/edgar/data/1394832/"
                        "000139483226000017/ats-pressreleasexfy26q4.htm"
                    ),
                    snippet="ATS reports fourth quarter fiscal 2026 results.",
                    publication_date="2026-05-28",
                )
            ][:max_results]
        if "market data valuation" in query.lower():
            return [
                SearchResult(
                    title="ATS Corporation Market Data",
                    publisher="Yahoo Finance",
                    url="https://finance.yahoo.com/quote/ATS.TO/",
                    snippet="Share price, valuation, and trading history for ATS Corporation.",
                )
            ][:max_results]
        if "peers competitors valuation" in query.lower():
            return [
                SearchResult(
                    title="ATS Corporation Competitors",
                    publisher="CompaniesMarketCap",
                    url="https://companiesmarketcap.com/ats/competitors/",
                    snippet="Comparable public companies and market value context.",
                )
            ][:max_results]
        return []


class _EarningsOnlySearchProvider:
    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        if "earnings release" in query.lower():
            return [
                SearchResult(
                    title="ATS Reports Fourth Quarter Fiscal 2026 Results",
                    publisher="U.S. Securities and Exchange Commission",
                    url=(
                        "https://www.sec.gov/Archives/edgar/data/1394832/"
                        "000139483226000017/ats-pressreleasexfy26q4.htm"
                    ),
                    snippet="ATS reports fourth quarter fiscal 2026 results.",
                )
            ][:max_results]
        if "sec 6-k" in query.lower():
            return [
                SearchResult(
                    title="ATS Corp /ATS latest Form 6-K",
                    publisher="U.S. Securities and Exchange Commission",
                    url=(
                        "https://www.sec.gov/Archives/edgar/data/1394832/"
                        "000162828026008830/a2026-2x17xraymondjamesins.htm"
                    ),
                    snippet="Direct SEC Form 6-K filing URL for ATS Corp /ATS.",
                )
            ][:max_results]
        return []


def _charter() -> ResearchCharter:
    return ResearchCharter(
        target="ATS Corporation",
        target_type="company",
        research_lens="investment",
        depth="standard",
        deliverable="investment_meeting_brief",
        key_questions=["Should we invest after the latest earnings release?"],
    )


def _plan() -> ResearchPlan:
    return ResearchPlan(
        research_questions=["What changed in the latest quarter?"],
        report_sections=["overview", "latest_results", "valuation", "peers"],
        required_source_types=[
            "Management discussion & analysis (MD&A) and earnings release/transcript",
            "market data / valuation screens / trading history",
            "peer company source set",
        ],
        checkpoint_questions=["Which valuation lens should be prioritized?"],
    )


def _source_map_without_current_sources() -> SourceMap:
    annual = SourceCandidate(
        id="src_annual",
        title="ATS annual report",
        publisher="ATS Corporation",
        url="https://www.sec.gov/Archives/edgar/data/1394832/annual.htm",
        source_type="corporate_filing",
        bias_risk="low",
        relevance_rationale="Annual filing.",
        recommended_uses=["business overview"],
        publication_date="2025-05-20",
    )
    return SourceMap(
        sources=[annual],
        scores=[
            SourceScore(
                source_id="src_annual",
                authority_score=5,
                relevance_score=4,
                recency_score=4,
                coverage_score=4,
                bias_risk="low",
                final_score=4.4,
                include=True,
            )
        ],
        gaps=[
            "Missing source type: earnings_release",
            "Missing source type: market_data",
            "Missing source type: peer_source",
        ],
    )


def test_repair_source_map_from_feedback_adds_current_investment_sources() -> None:
    provider = _AtsRepairSearchProvider()
    result = repair_source_map_from_feedback(
        charter=_charter(),
        plan=_plan(),
        source_map=_source_map_without_current_sources(),
        feedback=UserFeedback(
            user_notes="Earnings were just reported May 28 2026.",
            priority_topics=["valuation", "peer comparison"],
            approved_source_ids=["src_annual"],
        ),
        search_client=WebSearchClient(provider=provider),
    )

    repaired_by_type = {source.source_type: source for source in result.source_map.sources}

    assert repaired_by_type["earnings_release"].url.endswith(
        "ats-pressreleasexfy26q4.htm"
    )
    assert repaired_by_type["market_data"].publisher == "Yahoo Finance"
    assert repaired_by_type["peer_source"].publisher == "CompaniesMarketCap"
    assert result.repair_added_source_ids == [
        "repair_earnings_release_1",
        "repair_market_data_1",
        "repair_peer_source_1",
    ]
    assert not any("earnings_release" in gap for gap in result.source_map.gaps)
    assert "ATS Corporation May 28 2026 earnings release" in provider.queries
    assert result.review["repair_added_source_ids"] == result.repair_added_source_ids
    assert result.review["selected_sources"][0]["source_id"] == "src_annual"


def test_repair_ignores_generic_6k_and_adds_direct_market_fallbacks() -> None:
    result = repair_source_map_from_feedback(
        charter=_charter(),
        plan=_plan(),
        source_map=_source_map_without_current_sources(),
        feedback=UserFeedback(
            user_notes="Earnings were just reported May 28 2026.",
            priority_topics=["valuation", "peer comparison"],
            approved_source_ids=["src_annual"],
        ),
        search_client=WebSearchClient(provider=_EarningsOnlySearchProvider()),
    )

    by_type = {source.source_type: source for source in result.source_map.sources}

    assert "recent_sec_filing" not in by_type
    assert by_type["earnings_release"].url.endswith("ats-pressreleasexfy26q4.htm")
    assert by_type["market_data"].url == "https://finance.yahoo.com/quote/ATS/"
    assert by_type["peer_source"].url == "https://companiesmarketcap.com/ats/competitors/"


def test_build_source_discovery_review_records_queries_results_and_gaps(
    tmp_path: Path,
) -> None:
    source_map = _source_map_without_current_sources()
    review = build_source_discovery_review(
        queries=["ATS Corporation earnings release"],
        raw_search_results=[
            SearchResult(
                title="ATS Reports Fourth Quarter Fiscal 2026 Results",
                publisher="ATS Corporation",
                url="https://example.com/ats-q4-results",
                snippet="Latest quarterly results.",
            )
        ],
        selected_sources=source_map.sources,
        search_failures=[],
        source_map=source_map,
        repair_added_source_ids=["repair_earnings_release_1"],
        source_fetch_log=SourceFetchLog(
            results=[
                SourceFetchResult(
                    source_id="repair_earnings_release_1",
                    url="https://example.com/ats-q4-results",
                    status="fetched",
                    text_char_count=500,
                    chunk_count=1,
                )
            ]
        ),
        coverage_gaps=["Investment brief missing fetched market/valuation source."],
    )
    path = tmp_path / "source_discovery_review.json"
    path.write_text(json.dumps(review, indent=2), encoding="utf-8")

    saved = json.loads(path.read_text(encoding="utf-8"))

    assert saved["query_count"] == 1
    assert saved["raw_result_count"] == 1
    assert saved["repair_added_source_ids"] == ["repair_earnings_release_1"]
    assert saved["fetch_status_counts"] == {
        "fetched": 1,
        "fallback": 0,
        "failed": 0,
        "skipped": 0,
    }
    assert saved["unresolved_gaps"] == source_map.gaps
    assert saved["coverage_gaps"] == [
        "Investment brief missing fetched market/valuation source."
    ]


def test_investment_source_coverage_gaps_require_fetched_current_sources() -> None:
    source_map = _source_map_without_current_sources().model_copy(
        update={
            "sources": [
                *_source_map_without_current_sources().sources,
                SourceCandidate(
                    id="repair_earnings_release_1",
                    title="ATS Reports Fourth Quarter Fiscal 2026 Results",
                    publisher="ATS Corporation",
                    url="https://example.com/ats-q4-results",
                    source_type="earnings_release",
                    bias_risk="medium",
                    relevance_rationale="Latest earnings release.",
                    recommended_uses=["latest results"],
                ),
                SourceCandidate(
                    id="repair_market_data_1",
                    title="ATS market data",
                    publisher="Yahoo Finance",
                    url="https://finance.yahoo.com/quote/ATS.TO/",
                    source_type="market_data",
                    bias_risk="medium",
                    relevance_rationale="Valuation context.",
                    recommended_uses=["valuation"],
                ),
            ],
            "gaps": [],
        }
    )
    fetch_log = SourceFetchLog(
        results=[
            SourceFetchResult(
                source_id="repair_earnings_release_1",
                url="https://example.com/ats-q4-results",
                status="fetched",
                text_char_count=1200,
                chunk_count=1,
            )
        ]
    )

    gaps = investment_source_coverage_gaps(
        charter=_charter(),
        plan=_plan(),
        source_map=source_map,
        source_fetch_log=fetch_log,
    )

    assert gaps == [
        "Investment brief missing fetched market/valuation source.",
        "Investment brief missing fetched peer/comparable-company source.",
    ]
