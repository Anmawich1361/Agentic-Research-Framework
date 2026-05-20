from __future__ import annotations

from agentic_research.models import (
    EvidenceClaim,
    EvidenceLedger,
    SourceChunk,
    SourceContent,
    SourceFetchLog,
    SourceFetchResult,
)
from agentic_research.run_artifacts import (
    evidence_review_markdown,
    failure_report_markdown,
    has_blocking_evidence_warnings,
    report_revision_markdown,
    status_reason,
)
from agentic_research.report_validation import ReportSectionValidationError


def test_status_reason_documents_existing_run_statuses() -> None:
    assert (
        status_reason("needs_review")
        == "QA found blocking issues; final report was not written."
    )
    assert status_reason("unknown_status") == "Run status recorded."


def test_failure_report_markdown_preserves_failure_details() -> None:
    markdown = failure_report_markdown(
        run_id="run_test",
        request="Research Costco before a supplier meeting",
        error=RuntimeError("planner failed"),
    )

    assert "# Run Failure: run_test" in markdown
    assert "- Request: Research Costco before a supplier meeting" in markdown
    assert "- Error type: RuntimeError" in markdown
    assert "- Error message: planner failed" in markdown
    assert "No final report was written for this failed run." in markdown


def test_has_blocking_evidence_warnings_ignores_known_non_blocking_warnings() -> None:
    ledger = EvidenceLedger(
        validation_warnings=[
            "Dropped unsupported evidence claim ID r1 before synthesis: evidence quality category source_finding_aid.",
            "Renamed conflicting specialist evidence claim ID r2 to specialist_news_r2: claim/source content differed from the first occurrence.",
        ],
    )

    assert not has_blocking_evidence_warnings(ledger)

    blocking_ledger = EvidenceLedger(
        validation_warnings=[
            "Claim c1 is missing source id or URL.",
        ],
    )

    assert has_blocking_evidence_warnings(blocking_ledger)


def test_evidence_review_markdown_explains_empty_claims_with_fetched_content() -> None:
    ledger = EvidenceLedger(
        validation_warnings=[
            "No valid evidence claims were extracted from approved sources.",
        ]
    )
    source_content = [
        SourceContent(
            source_id="s1",
            url="https://example.com/source",
            content_type="text/html",
            title="Costco source",
            text="Costco supplier content.",
            excerpt="Costco supplier content.",
            chunks=[
                SourceChunk(
                    source_id="s1",
                    url="https://example.com/source",
                    chunk_id="s1_chunk_1",
                    index=0,
                    text="Costco supplier content.",
                )
            ],
        )
    ]

    markdown = evidence_review_markdown(
        ledger,
        source_content=source_content,
        source_fetch_log=SourceFetchLog(
            results=[
                SourceFetchResult(
                    source_id="s1",
                    url="https://example.com/source",
                    status="fetched",
                    text_char_count=24,
                    chunk_count=1,
                )
            ]
        ),
    )

    assert "No valid evidence claims were extracted from approved sources." in markdown
    assert "Fetched source content exists for 1 source" in markdown
    assert "evidence extraction prompt/source chunks" in markdown
    assert "Synthesis and QA were skipped" in markdown


def test_evidence_review_markdown_explains_empty_claims_without_fetched_content() -> None:
    ledger = EvidenceLedger(
        validation_warnings=[
            "No valid evidence claims were extracted from approved sources.",
        ]
    )

    markdown = evidence_review_markdown(
        ledger,
        source_content=[],
        source_fetch_log=SourceFetchLog(
            results=[
                SourceFetchResult(
                    source_id="s1",
                    url="https://example.com/source",
                    status="failed",
                    error="timeout",
                ),
                SourceFetchResult(
                    source_id="s2",
                    url="https://example.com/source-2",
                    status="skipped",
                    error="PDF ingestion is not implemented.",
                ),
            ]
        ),
    )

    assert "No valid evidence claims were extracted from approved sources." in markdown
    assert "No source content was fetched" in markdown
    assert "source discovery/source ingestion" in markdown
    assert "Fetch results: 0 fetched, 1 failed, 1 skipped" in markdown


def test_report_revision_markdown_uses_final_evidence_claim_ids() -> None:
    ledger = EvidenceLedger(
        claims=[
            EvidenceClaim(
                id="c1",
                claim="Costco has a membership warehouse model.",
                claim_type="fact",
                confidence="high",
                report_section="What We Know",
                source_id="s1",
                source_title="Costco Annual Report",
                source_url="https://example.com/costco",
                source_type="company",
                quote_or_excerpt="membership warehouses",
            ),
        ]
    )
    error = ReportSectionValidationError(message="Unknown claim reference: r1")

    markdown = report_revision_markdown(error=error, evidence_ledger=ledger)

    assert "Unknown claim reference: r1" in markdown
    assert "- c1" in markdown
    assert "- r1" not in markdown
