from agentic_research.models import SourceCandidate, SourceMap, SourceScore
from agentic_research.source_ingestion import SourceHttpResponse, ingest_source_content


def _source_map() -> SourceMap:
    return SourceMap(
        sources=[
            SourceCandidate(
                id="src_included",
                title="Included source",
                publisher="Example",
                url="https://example.com/included",
                source_type="primary_company",
                bias_risk="medium",
                relevance_rationale="Relevant source.",
                recommended_uses=["evidence"],
            ),
            SourceCandidate(
                id="src_held",
                title="Held source",
                publisher="Example",
                url="https://example.com/held",
                source_type="news",
                bias_risk="medium",
                relevance_rationale="Less relevant source.",
                recommended_uses=["background"],
            ),
        ],
        scores=[
            SourceScore(
                source_id="src_included",
                authority_score=4,
                relevance_score=5,
                recency_score=4,
                coverage_score=4,
                bias_risk="medium",
                final_score=4.2,
                include=True,
            ),
            SourceScore(
                source_id="src_held",
                authority_score=3,
                relevance_score=3,
                recency_score=3,
                coverage_score=3,
                bias_risk="medium",
                final_score=3.0,
                include=False,
            ),
        ],
        gaps=[],
    )


def test_ingest_source_content_fetches_included_html_and_removes_page_noise() -> None:
    calls: list[str] = []

    def fake_fetcher(url: str, timeout_seconds: float) -> SourceHttpResponse:
        calls.append(url)
        return SourceHttpResponse(
            url=url,
            status_code=200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=(
                "<html><head><title>Supplier standards</title><script>bad()</script></head>"
                "<body><nav>Navigation link</nav><main><h1>Supplier standards</h1>"
                "<p>Costco requires suppliers to meet delivery windows.</p>"
                "<p>Suppliers must provide accurate item data.</p></main>"
                "<footer>Footer links</footer></body></html>"
            ),
        )

    contents, log = ingest_source_content(_source_map(), fetcher=fake_fetcher)

    assert calls == ["https://example.com/included"]
    assert len(contents) == 1
    assert contents[0].source_id == "src_included"
    assert contents[0].title == "Supplier standards"
    assert "Costco requires suppliers to meet delivery windows." in contents[0].text
    assert "Navigation link" not in contents[0].text
    assert "Footer links" not in contents[0].text
    assert contents[0].chunks
    assert log.results[0].status == "fetched"


def test_ingest_source_content_logs_failed_fetch_without_raising() -> None:
    def failing_fetcher(url: str, timeout_seconds: float) -> SourceHttpResponse:
        raise TimeoutError("request timed out")

    contents, log = ingest_source_content(_source_map(), fetcher=failing_fetcher)

    assert contents == []
    assert len(log.results) == 1
    assert log.results[0].status == "failed"
    assert log.results[0].error is not None
    assert "request timed out" in log.results[0].error


def test_ingest_source_content_skips_pdf_without_crashing() -> None:
    source_map = _source_map()
    source_map.sources[0].url = "https://example.com/report.pdf"

    contents, log = ingest_source_content(
        source_map,
        fetcher=lambda url, timeout_seconds: SourceHttpResponse(
            url=url,
            status_code=200,
            headers={"content-type": "application/pdf"},
            text="%PDF",
        ),
    )

    assert contents == []
    assert log.results[0].status == "skipped"
    assert log.results[0].error == "PDF ingestion is not implemented."
