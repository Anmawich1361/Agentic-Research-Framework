from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlparse

from agentic_research.models import (
    BiasRisk,
    QAIssue,
    QAReview,
    ResearchCharter,
    ResearchPlan,
    SourceCandidate,
    SourceFetchLog,
    SourceMap,
    StrictModel,
    UserFeedback,
)
from agentic_research.source_scoring import (
    build_source_map,
    canonical_source_need,
    score_source,
)
from agentic_research.tools.web_search import (
    SearchFailure,
    SearchResult,
    WebSearchClient,
    build_source_search_queries,
)


EARNINGS_SOURCE_TYPES = {"earnings_release", "earnings_transcript", "recent_sec_filing"}
MARKET_SOURCE_TYPES = {"market_data"}
PEER_SOURCE_TYPES = {"peer_source", "competitor_source"}


class SourceRepairResult(StrictModel):
    source_map: SourceMap
    queries: list[str]
    raw_search_results: list[SearchResult]
    search_failures: list[SearchFailure]
    repair_added_source_ids: list[str]
    review: dict[str, Any]


def _dedupe_preserving_order(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _feedback_text(feedback: UserFeedback | None) -> str:
    if feedback is None:
        return ""
    answer_text = " ".join(
        answer.answer for answer in feedback.answered_checkpoint_questions
    )
    return " ".join(
        [
            answer_text,
            feedback.user_notes or "",
            " ".join(feedback.priority_topics),
        ]
    ).strip()


def _is_investment_context(charter: ResearchCharter) -> bool:
    text = " ".join(
        [
            charter.research_lens,
            charter.deliverable,
            *charter.key_questions,
        ]
    ).lower()
    return "invest" in text or "valuation" in text


def _plan_categories(plan: ResearchPlan) -> list[str]:
    return _dedupe_preserving_order(
        [canonical_source_need(source_type) for source_type in plan.required_source_types]
    )


def _text_mentions_any(text: str, terms: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def _repair_target_categories(
    *,
    charter: ResearchCharter,
    plan: ResearchPlan,
    source_map: SourceMap,
    feedback: UserFeedback | None,
) -> list[str]:
    feedback = feedback or UserFeedback()
    text = " ".join([_feedback_text(feedback), " ".join(source_map.gaps)]).lower()
    categories = set(_plan_categories(plan))
    if _text_mentions_any(text, ("earnings", "results", "reported", "quarter", "may ")):
        categories.update({"earnings_release", "recent_sec_filing"})
    if _text_mentions_any(text, ("valuation", "share price", "market data", "trading")):
        categories.add("market_data")
    if _text_mentions_any(text, ("peer", "peers", "competitor", "comparable")):
        categories.add("peer_source")
    if _is_investment_context(charter):
        categories.add("market_data")
    repairable_order = [
        "earnings_release",
        "recent_sec_filing",
        "earnings_transcript",
        "market_data",
        "peer_source",
        "investor_material",
        "industry_primer",
    ]
    return [category for category in repairable_order if category in categories]


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().replace("www.", "")


def _source_category_for_result(result: SearchResult) -> str | None:
    text = " ".join(
        [result.title, result.publisher, result.url, result.snippet or ""]
    ).lower()
    host = _host(result.url)
    if "transcript" in text:
        return "earnings_transcript"
    if (
        "earnings" in text
        or "quarterly results" in text
        or "financial results" in text
        or "pressrelease" in text
        or "press release" in text
        or "reports fourth quarter" in text
    ):
        return "earnings_release"
    if (
        "finance.yahoo" in host
        or "quote" in text
        or "market data" in text
        or "valuation" in text
        or "share price" in text
        or "trading history" in text
    ):
        return "market_data"
    if (
        "competitor" in text
        or "competitors" in text
        or "peer" in text
        or "comparable" in text
    ):
        return "peer_source"
    if "investor presentation" in text or "investor day" in text:
        return "investor_material"
    if "industry primer" in text or "market report" in text:
        return "industry_primer"
    return None


def _ticker_symbol_from_target(target: str) -> str | None:
    tokens = re.findall(r"[A-Za-z0-9]+", target)
    if not tokens:
        return None
    first = tokens[0]
    if first.isupper() and 1 <= len(first) <= 5:
        return first.upper()
    if len(tokens) == 1 and 1 <= len(first) <= 5:
        return first.upper()
    return None


def _direct_fallback_result_for_category(
    *,
    target: str,
    category: str,
) -> SearchResult | None:
    ticker = _ticker_symbol_from_target(target)
    if ticker is None:
        return None
    if category == "market_data":
        return SearchResult(
            title=f"{target} market data",
            publisher="Yahoo Finance",
            url=f"https://finance.yahoo.com/quote/{ticker}/",
            snippet=(
                f"Direct market-data fallback for {target}; fetch status must be "
                "reviewed before using valuation claims."
            ),
        )
    if category == "peer_source":
        return SearchResult(
            title=f"{target} competitors and peer valuation context",
            publisher="CompaniesMarketCap",
            url=f"https://companiesmarketcap.com/{ticker.lower()}/competitors/",
            snippet=(
                f"Direct peer-source fallback for {target}; fetch status must be "
                "reviewed before using peer comparison claims."
            ),
        )
    return None


def _bias_risk_for_result(result: SearchResult, category: str) -> BiasRisk:
    host = _host(result.url)
    if host.endswith("sec.gov"):
        return "low"
    if category in {"market_data", "peer_source", "investor_material"}:
        return "medium"
    return "medium"


def _recommended_uses_for_category(category: str) -> list[str]:
    return {
        "earnings_release": ["latest results", "recent financial performance"],
        "recent_sec_filing": ["recent SEC filing", "source verification"],
        "earnings_transcript": ["management commentary", "latest results"],
        "market_data": ["valuation", "trading history"],
        "peer_source": ["peer comparison", "valuation context"],
        "investor_material": ["management presentation", "company context"],
        "industry_primer": ["industry context"],
    }.get(category, ["source repair"])


def _category_label(category: str) -> str:
    return {
        "peer_source": "peer",
        "market_data": "market data",
        "earnings_release": "earnings release",
        "recent_sec_filing": "recent SEC filing",
        "earnings_transcript": "earnings transcript",
    }.get(category, category.replace("_", " "))


def _source_from_result(
    result: SearchResult,
    *,
    category: str,
    index: int,
) -> SourceCandidate:
    return SourceCandidate(
        id=f"repair_{category}_{index}",
        title=result.title,
        publisher=result.publisher,
        url=result.url,
        source_type=category,
        bias_risk=_bias_risk_for_result(result, category),
        relevance_rationale=f"Repair-added {_category_label(category)} source.",
        recommended_uses=_recommended_uses_for_category(category),
        publication_date=result.publication_date,
        notes="Added by source discovery repair.",
    )


def _normalize_url(url: str) -> str:
    return url.rstrip("/")


def _gap_resolved_by_categories(gap: str, categories: set[str]) -> bool:
    gap_lower = gap.lower()
    if gap_lower.startswith("missing source type:"):
        source_type = gap.split(":", 1)[1].strip()
        return canonical_source_need(source_type) in categories
    if "earnings" in gap_lower or "results" in gap_lower:
        return bool(EARNINGS_SOURCE_TYPES & categories)
    if "valuation" in gap_lower or "market" in gap_lower:
        return bool(MARKET_SOURCE_TYPES & categories)
    if "peer" in gap_lower or "competitor" in gap_lower:
        return bool(PEER_SOURCE_TYPES & categories)
    return False


def _merge_repaired_source_map(
    *,
    source_map: SourceMap,
    plan: ResearchPlan,
    added_sources: list[SourceCandidate],
) -> SourceMap:
    if not added_sources:
        return source_map
    sources = [*source_map.sources, *added_sources]
    rebuilt = build_source_map(
        sources,
        required_source_types=plan.required_source_types,
        mock=False,
    )
    added_scores = [
        score_source(source).model_copy(update={"include": True})
        for source in added_sources
    ]
    scores = sorted(
        [*source_map.scores, *added_scores],
        key=lambda score: score.final_score,
        reverse=True,
    )
    present_categories = {source.source_type for source in sources}
    preserved_gaps = [
        gap
        for gap in source_map.gaps
        if not _gap_resolved_by_categories(gap, present_categories)
    ]
    return rebuilt.model_copy(
        update={
            "scores": scores,
            "gaps": _dedupe_preserving_order([*preserved_gaps, *rebuilt.gaps]),
            "notes": "Live source map updated by source discovery repair.",
        }
    )


def _fetch_status_counts(source_fetch_log: SourceFetchLog | None) -> dict[str, int]:
    counts = {"fetched": 0, "fallback": 0, "failed": 0, "skipped": 0}
    if source_fetch_log is None:
        return counts
    for result in source_fetch_log.results:
        if result.status in counts:
            counts[result.status] += 1
    return counts


def build_source_discovery_review(
    *,
    queries: Sequence[str],
    raw_search_results: Sequence[SearchResult],
    selected_sources: Sequence[SourceCandidate],
    search_failures: Sequence[SearchFailure],
    source_map: SourceMap,
    repair_added_source_ids: Sequence[str] | None = None,
    source_fetch_log: SourceFetchLog | None = None,
    coverage_gaps: Sequence[str] | None = None,
) -> dict[str, Any]:
    repair_added = set(repair_added_source_ids or [])
    return {
        "query_count": len(queries),
        "queries": list(queries),
        "raw_result_count": len(raw_search_results),
        "raw_results": [
            result.model_dump(mode="json") for result in raw_search_results
        ],
        "search_failures": [
            failure.model_dump(mode="json") for failure in search_failures
        ],
        "selected_source_count": len(selected_sources),
        "selected_sources": [
            {
                "source_id": source.id,
                "title": source.title,
                "publisher": source.publisher,
                "url": source.url,
                "source_type": source.source_type,
                "repair_added": source.id in repair_added,
            }
            for source in selected_sources
        ],
        "repair_added_source_ids": list(repair_added_source_ids or []),
        "unresolved_gaps": list(source_map.gaps),
        "coverage_gaps": list(coverage_gaps or []),
        "fetch_status_counts": _fetch_status_counts(source_fetch_log),
    }


def repair_source_map_from_feedback(
    *,
    charter: ResearchCharter,
    plan: ResearchPlan,
    source_map: SourceMap,
    feedback: UserFeedback | None,
    search_client: WebSearchClient,
) -> SourceRepairResult:
    target_categories = _repair_target_categories(
        charter=charter,
        plan=plan,
        source_map=source_map,
        feedback=feedback,
    )
    feedback_text = _feedback_text(feedback)
    queries = build_source_search_queries(
        charter,
        plan,
        feedback_text=feedback_text,
    )
    raw_search_results = search_client.search_many(queries)
    search_failures = list(search_client.last_failures)
    existing_urls = {_normalize_url(source.url) for source in source_map.sources}
    present_categories = {source.source_type for source in source_map.sources}
    added_sources: list[SourceCandidate] = []
    category_counts: dict[str, int] = {}
    for result in raw_search_results:
        category = _source_category_for_result(result)
        if category is None or category not in target_categories:
            continue
        if category in present_categories:
            continue
        if _normalize_url(result.url) in existing_urls:
            continue
        category_counts[category] = category_counts.get(category, 0) + 1
        source = _source_from_result(
            result,
            category=category,
            index=category_counts[category],
        )
        added_sources.append(source)
        present_categories.add(category)
        existing_urls.add(_normalize_url(result.url))
    for category in ("market_data", "peer_source"):
        if category not in target_categories or category in present_categories:
            continue
        fallback_result = _direct_fallback_result_for_category(
            target=charter.target,
            category=category,
        )
        if fallback_result is None or _normalize_url(fallback_result.url) in existing_urls:
            continue
        raw_search_results.append(fallback_result)
        category_counts[category] = category_counts.get(category, 0) + 1
        source = _source_from_result(
            fallback_result,
            category=category,
            index=category_counts[category],
        )
        added_sources.append(source)
        present_categories.add(category)
        existing_urls.add(_normalize_url(fallback_result.url))
    repaired_map = _merge_repaired_source_map(
        source_map=source_map,
        plan=plan,
        added_sources=added_sources,
    )
    repair_added_source_ids = [source.id for source in added_sources]
    review = build_source_discovery_review(
        queries=queries,
        raw_search_results=raw_search_results,
        selected_sources=repaired_map.sources,
        search_failures=search_failures,
        source_map=repaired_map,
        repair_added_source_ids=repair_added_source_ids,
    )
    return SourceRepairResult(
        source_map=repaired_map,
        queries=queries,
        raw_search_results=raw_search_results,
        search_failures=search_failures,
        repair_added_source_ids=repair_added_source_ids,
        review=review,
    )


def _fetched_source_types(
    *,
    source_map: SourceMap,
    source_fetch_log: SourceFetchLog | None,
) -> set[str]:
    source_types_by_id = {source.id: source.source_type for source in source_map.sources}
    fetched_source_ids = {
        result.source_id
        for result in (source_fetch_log.results if source_fetch_log is not None else [])
        if result.status == "fetched" and result.text_char_count > 0
    }
    return {
        source_types_by_id[source_id]
        for source_id in fetched_source_ids
        if source_id in source_types_by_id
    }


def investment_source_coverage_gaps(
    *,
    charter: ResearchCharter,
    plan: ResearchPlan,
    source_map: SourceMap,
    source_fetch_log: SourceFetchLog | None,
) -> list[str]:
    required_categories = set(_plan_categories(plan))
    gap_text = " ".join(source_map.gaps).lower()
    if not _is_investment_context(charter):
        return []
    fetched_types = _fetched_source_types(
        source_map=source_map,
        source_fetch_log=source_fetch_log,
    )
    gaps: list[str] = []
    if (
        "earnings_release" in required_categories
        or "earnings_transcript" in required_categories
        or "earnings" in gap_text
        or "results" in gap_text
    ) and not (EARNINGS_SOURCE_TYPES & fetched_types):
        gaps.append("Investment brief missing fetched latest earnings release or transcript source.")
    if (
        "market_data" in required_categories or _is_investment_context(charter)
    ) and not (MARKET_SOURCE_TYPES & fetched_types):
        gaps.append("Investment brief missing fetched market/valuation source.")
    if (
        "peer_source" in required_categories or "peer" in gap_text
    ) and not (PEER_SOURCE_TYPES & fetched_types):
        gaps.append("Investment brief missing fetched peer/comparable-company source.")
    return gaps


def qa_review_with_source_coverage_gaps(
    qa_review: QAReview | None,
    coverage_gaps: Sequence[str],
) -> QAReview | None:
    if not coverage_gaps:
        return qa_review
    coverage_issues = [
        QAIssue(
            severity="high",
            category="source_gap",
            problem=gap,
            suggested_fix="Add and fetch the missing source category before publishing.",
            affected_section="Source Coverage",
        )
        for gap in coverage_gaps
    ]
    if qa_review is None:
        return QAReview(
            ready_to_publish=False,
            issues=coverage_issues,
            summary="Source coverage gaps block publication.",
        )
    return qa_review.model_copy(
        update={
            "ready_to_publish": False,
            "issues": [*qa_review.issues, *coverage_issues],
            "summary": qa_review.summary or "Source coverage gaps block publication.",
        }
    )


__all__ = [
    "SourceRepairResult",
    "build_source_discovery_review",
    "investment_source_coverage_gaps",
    "qa_review_with_source_coverage_gaps",
    "repair_source_map_from_feedback",
]
