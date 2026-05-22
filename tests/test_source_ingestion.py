from agentic_research.models import SourceCandidate, SourceMap, SourceScore
from agentic_research.source_ingestion import (
    SourceHttpResponse,
    ingest_source_content,
    sources_for_ingestion,
)


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
    assert contents[0].excerpt is not None
    assert "Costco requires suppliers to meet delivery windows." in contents[0].excerpt
    assert "Navigation link" not in contents[0].text
    assert "Footer links" not in contents[0].text
    assert contents[0].chunks
    assert contents[0].chunks[0].text
    assert log.results[0].status == "fetched"
    assert log.results[0].text_char_count == len(contents[0].text)
    assert log.results[0].chunk_count == len(contents[0].chunks)


def test_source_fetch_log_does_not_duplicate_full_text_or_chunks() -> None:
    body = "".join(f"<p>Paragraph {index} has useful supplier detail.</p>" for index in range(80))

    def fake_fetcher(url: str, timeout_seconds: float) -> SourceHttpResponse:
        return SourceHttpResponse(
            url="https://example.com/redirected",
            status_code=200,
            headers={"content-type": "text/html"},
            text=f"<html><head><title>Supplier standards</title></head><body>{body}</body></html>",
        )

    contents, log = ingest_source_content(_source_map(), fetcher=fake_fetcher)

    content_payload = contents[0].model_dump()
    log_payload = log.model_dump()
    log_result = log_payload["results"][0]
    assert "text" in content_payload
    assert "excerpt" in content_payload
    assert "chunks" in content_payload
    assert content_payload["text"] == contents[0].text
    assert content_payload["excerpt"] == contents[0].excerpt
    assert content_payload["chunks"] == [
        chunk.model_dump() for chunk in contents[0].chunks
    ]
    assert "text" not in log_result
    assert "chunks" not in log_result
    assert log_result["text_char_count"] == len(contents[0].text)
    assert log_result["chunk_count"] == len(contents[0].chunks)
    assert len(log_result["excerpt"]) <= 240
    assert log_result["fetched_url"] == "https://example.com/redirected"


def test_ingest_source_content_logs_failed_fetch_without_raising() -> None:
    def failing_fetcher(url: str, timeout_seconds: float) -> SourceHttpResponse:
        raise TimeoutError("request timed out")

    contents, log = ingest_source_content(_source_map(), fetcher=failing_fetcher)

    assert contents == []
    assert len(log.results) == 1
    assert log.results[0].status == "failed"
    assert log.results[0].error is not None
    assert "request timed out" in log.results[0].error
    assert log.results[0].text_char_count == 0
    assert log.results[0].chunk_count == 0
    log_payload = log.model_dump()
    assert "text" not in log_payload["results"][0]
    assert "chunks" not in log_payload["results"][0]


def test_ingest_source_content_logs_http_403_failure_reason_without_crashing() -> None:
    def blocked_fetcher(url: str, timeout_seconds: float) -> SourceHttpResponse:
        return SourceHttpResponse(
            url=url,
            status_code=403,
            headers={"content-type": "text/html"},
            text="<html><body>Forbidden</body></html>",
        )

    contents, log = ingest_source_content(_source_map(), fetcher=blocked_fetcher)

    assert contents == []
    assert log.results[0].status == "failed"
    assert log.results[0].error == "HTTP 403"
    assert log.results[0].failure_reason == "http_403"
    assert log.results[0].text_char_count == 0
    assert log.results[0].chunk_count == 0


def test_ingest_source_content_logs_no_readable_text_failure_reason() -> None:
    def empty_fetcher(url: str, timeout_seconds: float) -> SourceHttpResponse:
        return SourceHttpResponse(
            url=url,
            status_code=200,
            headers={"content-type": "text/html"},
            text=(
                "<html><head><title>Costco Wholesale Corporation - Investor "
                "Relations</title></head><body><nav>Navigation only</nav></body></html>"
            ),
        )

    contents, log = ingest_source_content(_source_map(), fetcher=empty_fetcher)

    assert contents == []
    assert log.results[0].status == "failed"
    assert log.results[0].failure_reason == "no_readable_text"
    assert log.results[0].title == "Costco Wholesale Corporation - Investor Relations"
    assert log.results[0].error == "No readable text extracted."


def test_ingest_source_content_logs_bad_url_without_fetching() -> None:
    source_map = _source_map()
    source_map.sources[0].url = "not-a-valid-url"

    def fetcher_should_not_run(url: str, timeout_seconds: float) -> SourceHttpResponse:
        raise AssertionError("Bad URLs should fail before fetch.")

    contents, log = ingest_source_content(source_map, fetcher=fetcher_should_not_run)

    assert contents == []
    assert log.results[0].status == "failed"
    assert log.results[0].failure_reason == "bad_url"
    assert log.results[0].error == "Invalid source URL."


def test_ingest_source_content_extracts_pdf_text_when_extractor_available() -> None:
    source_map = _source_map()
    source_map.sources[0].url = "https://example.com/report.pdf"

    contents, log = ingest_source_content(
        source_map,
        fetcher=lambda url, timeout_seconds: SourceHttpResponse(
            url=url,
            status_code=200,
            headers={"content-type": "application/pdf"},
            text="",
            content=b"%PDF fixture bytes",
        ),
        pdf_text_extractor=lambda content: (
            "Costco Vendor Code of Conduct\n"
            "Suppliers must comply with Costco's vendor expectations."
        ),
    )

    assert len(contents) == 1
    assert contents[0].content_type == "application/pdf"
    assert "Suppliers must comply" in contents[0].text
    assert contents[0].chunks
    assert log.results[0].status == "fetched"
    assert log.results[0].failure_reason is None
    assert log.results[0].text_char_count == len(contents[0].text)
    assert log.results[0].chunk_count == len(contents[0].chunks)
    log_payload = log.model_dump()
    assert "text" not in log_payload["results"][0]
    assert "chunks" not in log_payload["results"][0]


def test_ingest_source_content_logs_pdf_extraction_failure_and_continues() -> None:
    source_map = _source_map()
    source_map.sources[0].url = "https://example.com/report.pdf"

    def broken_pdf_extractor(content: bytes) -> str:
        raise ValueError("fixture PDF parse failed")

    contents, log = ingest_source_content(
        source_map,
        fetcher=lambda url, timeout_seconds: SourceHttpResponse(
            url=url,
            status_code=200,
            headers={"content-type": "application/pdf"},
            text="",
            content=b"%PDF fixture bytes",
        ),
        pdf_text_extractor=broken_pdf_extractor,
    )

    assert contents == []
    assert log.results[0].status == "failed"
    assert log.results[0].failure_reason == "pdf_extraction_failed"
    assert "fixture PDF parse failed" in (log.results[0].error or "")


def test_sources_for_ingestion_prefers_sec_filing_before_investor_relations() -> None:
    source_map = SourceMap(
        sources=[
            SourceCandidate(
                id="costco-ir",
                title="Costco investor relations",
                publisher="Costco",
                url="https://investor.costco.com/financials/sec-filings/default.aspx",
                source_type="investor_material",
                bias_risk="medium",
                relevance_rationale="Investor relations filing index.",
                recommended_uses=["company updates"],
            ),
            SourceCandidate(
                id="costco-sec-10k",
                title="Costco 10-K",
                publisher="SEC",
                url="https://www.sec.gov/Archives/edgar/data/909832/000090983225000019/cost-20250831.htm",
                source_type="corporate_filing",
                bias_risk="low",
                relevance_rationale="Accessible official SEC filing.",
                recommended_uses=["financials", "business overview"],
            ),
        ],
        scores=[
            SourceScore(
                source_id="costco-ir",
                authority_score=4,
                relevance_score=5,
                recency_score=5,
                coverage_score=4,
                bias_risk="medium",
                final_score=4.5,
                include=True,
            ),
            SourceScore(
                source_id="costco-sec-10k",
                authority_score=5,
                relevance_score=4,
                recency_score=3,
                coverage_score=4,
                bias_risk="low",
                final_score=4.0,
                include=True,
            ),
        ],
        gaps=[],
    )

    selected = sources_for_ingestion(source_map)

    assert [source.id for source in selected] == ["costco-sec-10k", "costco-ir"]


def test_ingest_source_content_repairs_bad_sec_archive_url_with_resolved_filing() -> None:
    source_map = SourceMap(
        sources=[
            SourceCandidate(
                id="costco-sec-10k",
                title="Costco 10-K",
                publisher="SEC",
                url="https://www.sec.gov/Archives/edgar/data/909832/000090983224000015/costco-20230903.htm",
                source_type="corporate_filing",
                bias_risk="low",
                relevance_rationale="Official filing.",
                recommended_uses=["business overview"],
            )
        ],
        scores=[
            SourceScore(
                source_id="costco-sec-10k",
                authority_score=5,
                relevance_score=5,
                recency_score=4,
                coverage_score=5,
                bias_risk="low",
                final_score=4.6,
                include=True,
            )
        ],
        gaps=[],
    )
    repaired_url = (
        "https://www.sec.gov/Archives/edgar/data/909832/"
        "000090983225000101/cost-20250831.htm"
    )
    calls: list[str] = []

    def fake_fetcher(url: str, timeout_seconds: float) -> SourceHttpResponse:
        calls.append(url)
        if url == source_map.sources[0].url:
            return SourceHttpResponse(
                url=url,
                status_code=404,
                headers={"content-type": "application/xml"},
                text="<Error><Code>NoSuchKey</Code></Error>",
            )
        return SourceHttpResponse(
            url=url,
            status_code=200,
            headers={"content-type": "text/html"},
            text=(
                "<html><head><title>Costco 10-K</title></head><body><main>"
                "<p>Costco operates membership warehouses and sells food and "
                "non-food merchandise.</p></main></body></html>"
            ),
        )

    contents, log = ingest_source_content(
        source_map,
        fetcher=fake_fetcher,
        sec_filing_resolver=lambda url, timeout_seconds: repaired_url,
    )

    assert calls == [source_map.sources[0].url, repaired_url]
    assert len(contents) == 1
    assert contents[0].source_id == "costco-sec-10k"
    assert contents[0].url == repaired_url
    assert contents[0].chunks[0].url == repaired_url
    assert "Costco operates membership warehouses" in contents[0].text
    assert log.results[0].status == "fetched"
    assert log.results[0].fetched_url == repaired_url
