from agentic_research.models import (
    SourceCandidate,
    SourceChunk,
    SourceContent,
    SourceFallbackContext,
    SourceFetchLog,
    SourceFetchResult,
    SourceMap,
    SourceScore,
)
from agentic_research.source_context import (
    source_content_payload,
    source_fetch_log_with_fallbacks,
    source_map_with_fetched_urls,
    synthesis_source_evidence_context,
    weak_fallback_contexts,
)
from agentic_research.tools.web_search import SearchResult


def _source_map() -> SourceMap:
    return SourceMap(
        sources=[
            SourceCandidate(
                id="src_primary",
                title="Costco investor relations",
                publisher="Costco",
                url="https://investor.costco.com",
                source_type="investor_material",
                bias_risk="low",
                relevance_rationale="Direct company source.",
                recommended_uses=["current support"],
            ),
            SourceCandidate(
                id="src_blocked",
                title="Costco supplier page",
                publisher="Costco",
                url="https://www.costco.com/suppliers.html",
                source_type="primary_company",
                bias_risk="medium",
                relevance_rationale="Supplier context.",
                recommended_uses=["supplier context"],
            ),
            SourceCandidate(
                id="src_secondary",
                title="Transcript index",
                publisher="Example",
                url="https://example.com/transcripts",
                source_type="earnings_transcript",
                bias_risk="medium",
                relevance_rationale="Secondary transcript index.",
                recommended_uses=["recent commentary"],
            ),
        ],
        scores=[
            SourceScore(
                source_id="src_primary",
                authority_score=5,
                relevance_score=5,
                recency_score=4,
                coverage_score=4,
                bias_risk="low",
                final_score=4.5,
                include=True,
            ),
            SourceScore(
                source_id="src_blocked",
                authority_score=4,
                relevance_score=4,
                recency_score=4,
                coverage_score=3,
                bias_risk="medium",
                final_score=4.0,
                include=True,
            ),
            SourceScore(
                source_id="src_secondary",
                authority_score=3,
                relevance_score=4,
                recency_score=4,
                coverage_score=3,
                bias_risk="medium",
                final_score=3.4,
                include=True,
            ),
        ],
        gaps=[],
    )


def test_source_context_updates_fetched_urls_and_shapes_chunk_payload() -> None:
    content = SourceContent(
        source_id="src_primary",
        url="https://investor.costco.com/redirected",
        content_type="text/html",
        title="Costco investor relations",
        text="",
        chunks=[
            SourceChunk(
                source_id="src_primary",
                url="https://investor.costco.com/redirected",
                chunk_id="noise",
                index=0,
                text=("0000909832 us-gaap fasb.org " * 80),
            ),
            SourceChunk(
                source_id="src_primary",
                url="https://investor.costco.com/redirected",
                chunk_id="signal",
                index=1,
                text="Costco discusses earnings, net sales, membership, and warehouses.",
            ),
        ],
    )

    updated = source_map_with_fetched_urls(_source_map(), [content])
    payload = source_content_payload([content], max_chunks_per_source=1)

    assert updated.sources[0].url == "https://investor.costco.com/redirected"
    assert payload[0]["chunks"][0]["chunk_id"] == "signal"
    assert "text" not in payload[0]


def test_source_content_payload_preserves_later_source_coverage() -> None:
    contents = [
        SourceContent(
            source_id="src_annual",
            url="https://example.com/annual",
            content_type="text/html",
            title="Annual report",
            text="",
            chunks=[
                SourceChunk(
                    source_id="src_annual",
                    url="https://example.com/annual",
                    chunk_id=f"annual_{index}",
                    index=index,
                    text="annual business earnings discussion " * 100,
                )
                for index in range(5)
            ],
        ),
        SourceContent(
            source_id="src_current_release",
            url="https://example.com/release",
            content_type="text/html",
            title="Current quarter release",
            text="",
            chunks=[
                SourceChunk(
                    source_id="src_current_release",
                    url="https://example.com/release",
                    chunk_id="release_metrics",
                    index=0,
                    text="Q4 revenue, adjusted EBITDA, order bookings, backlog, and guidance.",
                )
            ],
        ),
        SourceContent(
            source_id="src_transcript",
            url="https://example.com/transcript",
            content_type="text/html",
            title="Current quarter transcript",
            text="",
            chunks=[
                SourceChunk(
                    source_id="src_transcript",
                    url="https://example.com/transcript",
                    chunk_id="transcript_commentary",
                    index=0,
                    text="Management commentary on margin expansion, working capital, and demand.",
                )
            ],
        ),
    ]

    payload = source_content_payload(
        contents,
        max_total_chars=2500,
        max_chunks_per_source=3,
        max_chunk_chars=1000,
    )

    chunks_by_source = {
        item["source_id"]: [chunk["chunk_id"] for chunk in item["chunks"]]
        for item in payload
    }

    assert chunks_by_source["src_current_release"] == ["release_metrics"]
    assert chunks_by_source["src_transcript"] == ["transcript_commentary"]


def test_source_content_payload_prioritizes_current_financial_metrics() -> None:
    content = SourceContent(
        source_id="src_current_release",
        url="https://example.com/release",
        content_type="text/html",
        title="Current quarter release",
        text="",
        chunks=[
            SourceChunk(
                source_id="src_current_release",
                url="https://example.com/release",
                chunk_id="definitions",
                index=0,
                text=(
                    "The terms EBITDA, organic revenue, adjusted net income, "
                    "adjusted earnings from operations, adjusted revenues, "
                    "adjusted EBITDA, adjusted basic earnings per share, and "
                    "free cash flow are non-IFRS financial measures. "
                )
                * 5,
            ),
            SourceChunk(
                source_id="src_current_release",
                url="https://example.com/release",
                chunk_id="current_metrics",
                index=1,
                text=(
                    "Fourth quarter revenues were $747.1 million; adjusted "
                    "revenues were $744.3 million; adjusted EBITDA was "
                    "$102.5 million; Order Bookings were $704 million; "
                    "Order Backlog was $1,958 million; fiscal 2027 revenue "
                    "guidance is $700 million to $740 million."
                ),
            ),
        ],
    )

    payload = source_content_payload([content], max_chunks_per_source=1)

    assert payload[0]["chunks"][0]["chunk_id"] == "current_metrics"


def test_source_content_payload_prioritizes_dated_financial_metrics_without_fixed_year() -> None:
    content = SourceContent(
        source_id="src_current_release",
        url="https://example.com/release",
        content_type="text/html",
        title="Current quarter release",
        text="",
        chunks=[
            SourceChunk(
                source_id="src_current_release",
                url="https://example.com/release",
                chunk_id="definitions",
                index=0,
                text=(
                    "The terms EBITDA, organic revenue, adjusted net income, "
                    "adjusted earnings from operations, adjusted revenues, "
                    "adjusted EBITDA, adjusted basic earnings per share, and "
                    "free cash flow are non-IFRS financial measures. "
                )
                * 5,
            ),
            SourceChunk(
                source_id="src_current_release",
                url="https://example.com/release",
                chunk_id="dated_metrics",
                index=1,
                text=(
                    "Fiscal 2028 revenue guidance depends on order backlog, "
                    "order bookings, and working capital conversion."
                ),
            ),
        ],
    )

    payload = source_content_payload([content], max_chunks_per_source=1)

    assert payload[0]["chunks"][0]["chunk_id"] == "dated_metrics"


def test_source_context_marks_search_snippet_fallbacks_without_direct_evidence() -> None:
    source_map = _source_map()
    fetch_log = SourceFetchLog(
        results=[
            SourceFetchResult(
                source_id="src_blocked",
                url="https://www.costco.com/suppliers.html",
                status="failed",
                failure_reason="http_403",
            ),
            SourceFetchResult(
                source_id="src_secondary",
                url="https://example.com/transcripts",
                status="fetched",
                content_type="text/html",
            ),
        ]
    )
    contexts = weak_fallback_contexts(
        source_map=source_map,
        raw_search_results=[
            SearchResult(
                title="Costco supplier page",
                publisher="Costco",
                url="https://www.costco.com/suppliers.html",
                snippet="Supplier standards and vendor information.",
            )
        ],
        source_content=[
            SourceContent(
                source_id="src_secondary",
                url="https://example.com/transcripts",
                content_type="text/html",
                title="Transcript index",
                text="Secondary transcript page.",
            )
        ],
        source_fetch_log=fetch_log,
    )
    fallback_log = source_fetch_log_with_fallbacks(fetch_log, contexts)
    evidence_context = synthesis_source_evidence_context(
        source_map=source_map,
        source_content=[
            SourceContent(
                source_id="src_secondary",
                url="https://example.com/transcripts",
                content_type="text/html",
                title="Transcript index",
                text="Secondary transcript page.",
            )
        ],
        source_fetch_log=fallback_log,
    )

    assert contexts == [
        SourceFallbackContext(
            source_id="src_blocked",
            url="https://www.costco.com/suppliers.html",
            title="Costco supplier page",
            publisher="Costco",
            snippet="Supplier standards and vendor information.",
            context_type="search_snippet_only",
            caveats=[
                "Search-result snippets are not fetched source text.",
                "Do not use this context for high-confidence factual claims.",
            ],
        )
    ]
    assert fallback_log is not None
    assert [result.status for result in fallback_log.results] == ["fallback", "fetched"]
    assert evidence_context["secondary_or_indirect_only"] is True
    assert "src_blocked" in evidence_context["failed_or_skipped_source_ids"]
