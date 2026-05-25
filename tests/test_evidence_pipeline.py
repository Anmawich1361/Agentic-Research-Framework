from agentic_research.evidence_pipeline import (
    DIRECT_EVIDENCE_SUFFICIENCY_WARNING,
    enforce_direct_company_evidence,
    validate_evidence,
)
from agentic_research.models import (
    EvidenceClaim,
    EvidenceLedger,
    ResearchCharter,
    SourceCandidate,
    SourceFetchLog,
    SourceFetchResult,
    SourceMap,
    SourceScore,
)


def _source_map() -> SourceMap:
    return SourceMap(
        sources=[
            SourceCandidate(
                id="src_sec",
                title="Costco 10-K",
                publisher="SEC",
                url=(
                    "https://www.sec.gov/Archives/edgar/data/909832/"
                    "000090983225000101/cost-20250831.htm"
                ),
                source_type="corporate_filing",
                bias_risk="low",
                relevance_rationale="Primary filing.",
                recommended_uses=["business facts"],
            ),
            SourceCandidate(
                id="src_failed",
                title="Costco supplier page",
                publisher="Costco",
                url="https://www.costco.com/suppliers.html",
                source_type="primary_company",
                bias_risk="medium",
                relevance_rationale="Supplier context.",
                recommended_uses=["supplier meeting"],
            ),
            SourceCandidate(
                id="src_indirect",
                title="Warehouse club primer",
                publisher="Example",
                url="https://example.com/warehouse-clubs",
                source_type="industry_primer",
                bias_risk="medium",
                relevance_rationale="Industry background.",
                recommended_uses=["market context"],
            ),
        ],
        scores=[
            SourceScore(
                source_id="src_sec",
                authority_score=5,
                relevance_score=5,
                recency_score=4,
                coverage_score=5,
                bias_risk="low",
                final_score=4.8,
                include=True,
            ),
            SourceScore(
                source_id="src_failed",
                authority_score=4,
                relevance_score=4,
                recency_score=4,
                coverage_score=3,
                bias_risk="medium",
                final_score=4.0,
                include=True,
            ),
            SourceScore(
                source_id="src_indirect",
                authority_score=3,
                relevance_score=4,
                recency_score=3,
                coverage_score=3,
                bias_risk="medium",
                final_score=3.3,
                include=True,
            ),
        ],
        gaps=[],
    )


def test_validate_evidence_repairs_stale_sec_urls_and_blocks_failed_sources() -> None:
    stale_sec_url = (
        "https://www.sec.gov/Archives/edgar/data/909832/"
        "000090983025000101/cost-20250831.htm"
    )

    ledger = validate_evidence(
        [
            EvidenceClaim(
                id="sec_fact",
                claim="Costco operates membership warehouses and sells merchandise.",
                claim_type="fact",
                source_id="src_sec",
                source_url=stale_sec_url,
                source_type="corporate_filing",
                confidence="high",
                report_section="business_overview",
                quote_or_excerpt="membership warehouses",
            ),
            EvidenceClaim(
                id="failed_fact",
                claim="Costco supplier standards page indicates a vendor quality program.",
                claim_type="fact",
                source_id="src_failed",
                source_url="https://www.costco.com/suppliers.html",
                source_type="primary_company",
                confidence="medium",
                report_section="supplier_context",
            ),
        ],
        source_map=_source_map(),
        source_fetch_log=SourceFetchLog(
            results=[
                SourceFetchResult(
                    source_id="src_failed",
                    url="https://www.costco.com/suppliers.html",
                    status="failed",
                    failure_reason="http_403",
                )
            ]
        ),
    )

    assert [claim.id for claim in ledger.claims] == ["sec_fact"]
    assert ledger.claims[0].source_url == _source_map().sources[0].url
    assert any("Repaired stale source_url" in warning for warning in ledger.validation_warnings)
    assert any("failed_fact" in warning for warning in ledger.validation_warnings)


def test_enforce_direct_company_evidence_flags_indirect_company_reports() -> None:
    ledger = EvidenceLedger(
        claims=[
            EvidenceClaim(
                id="industry_fact",
                claim="Warehouse clubs sell bulk-pack merchandise to members.",
                claim_type="fact",
                source_id="src_indirect",
                source_url="https://example.com/warehouse-clubs",
                source_type="industry_primer",
                confidence="medium",
                report_section="market_context",
            )
        ]
    )
    charter = ResearchCharter(
        target="Costco",
        target_type="company",
        research_lens="sales",
        depth="brief",
        deliverable="meeting_prep_brief",
        key_questions=["What should suppliers know?"],
    )

    updated = enforce_direct_company_evidence(
        ledger,
        charter=charter,
        source_map=_source_map(),
    )

    assert DIRECT_EVIDENCE_SUFFICIENCY_WARNING in updated.validation_warnings
