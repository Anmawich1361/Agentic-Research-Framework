from agentic_research.conservative_report import (
    can_apply_supplier_meeting_fallback,
    create_conservative_report,
)
from agentic_research.models import (
    EvidenceClaim,
    EvidenceLedger,
    ResearchCharter,
    ResearchPlan,
    SourceCandidate,
    SourceFetchLog,
    SourceFetchResult,
    SourceMap,
    SourceScore,
)


def _charter(*, deliverable: str = "meeting_prep_brief") -> ResearchCharter:
    return ResearchCharter(
        target="TargetCo",
        target_type="company",
        research_lens="sales",
        depth="brief",
        deliverable=deliverable,
        key_questions=["What matters before the supplier meeting?"],
    )


def _plan() -> ResearchPlan:
    return ResearchPlan(
        research_questions=["What should suppliers understand?"],
        report_sections=["overview", "supplier_context"],
        required_source_types=["primary_company", "news"],
        checkpoint_questions=["Which buyer owns the category?"],
        data_gaps=["Category timing not specified."],
    )


def _source_map() -> SourceMap:
    return SourceMap(
        sources=[
            SourceCandidate(
                id="src_primary",
                title="TargetCo supplier page",
                publisher="TargetCo",
                url="https://www.targetco.example/suppliers",
                source_type="primary_company",
                bias_risk="medium",
                relevance_rationale="Direct supplier context.",
                recommended_uses=["supplier context"],
            ),
            SourceCandidate(
                id="src_recent",
                title="TargetCo recent earnings",
                publisher="TargetCo",
                url="https://investor.targetco.example/recent",
                source_type="earnings_release",
                bias_risk="low",
                relevance_rationale="Recent earnings.",
                recommended_uses=["recent context"],
            ),
            SourceCandidate(
                id="src_secondary",
                title="Industry background",
                publisher="Example",
                url="https://example.com/industry",
                source_type="industry_primer",
                bias_risk="medium",
                relevance_rationale="Background context.",
                recommended_uses=["market context"],
            ),
        ],
        scores=[
            SourceScore(
                source_id="src_primary",
                authority_score=4,
                relevance_score=5,
                recency_score=4,
                coverage_score=3,
                bias_risk="medium",
                final_score=4.0,
                include=True,
            ),
            SourceScore(
                source_id="src_recent",
                authority_score=5,
                relevance_score=5,
                recency_score=5,
                coverage_score=4,
                bias_risk="low",
                final_score=4.8,
                include=True,
            ),
            SourceScore(
                source_id="src_secondary",
                authority_score=3,
                relevance_score=4,
                recency_score=3,
                coverage_score=3,
                bias_risk="medium",
                final_score=3.3,
                include=True,
            ),
        ],
        gaps=["Recent earnings text was not fetched."],
    )


def test_conservative_report_keeps_only_direct_cautious_meeting_claims() -> None:
    report = create_conservative_report(
        charter=_charter(),
        plan=_plan(),
        source_map=_source_map(),
        evidence_ledger=EvidenceLedger(
            claims=[
                EvidenceClaim(
                    id="c_supplier",
                    claim="TargetCo says suppliers must meet quality standards.",
                    claim_type="fact",
                    source_id="src_primary",
                    source_url="https://www.targetco.example/suppliers",
                    source_type="primary_company",
                    confidence="medium",
                    report_section="supplier_context",
                    quote_or_excerpt="quality standards",
                ),
                EvidenceClaim(
                    id="c_recent",
                    claim="TargetCo current strategy prioritizes e-commerce momentum.",
                    claim_type="fact",
                    source_id="src_recent",
                    source_url="https://investor.targetco.example/recent",
                    source_type="earnings_release",
                    confidence="medium",
                    report_section="Recent Developments",
                    quote_or_excerpt="e-commerce momentum",
                ),
                EvidenceClaim(
                    id="c_secondary",
                    claim="The industry primer says bulk retail customers buy in bulk.",
                    claim_type="fact",
                    source_id="src_secondary",
                    source_url="https://example.com/industry",
                    source_type="industry_primer",
                    confidence="medium",
                    report_section="market_context",
                    quote_or_excerpt="buy in bulk",
                ),
            ]
        ),
        source_fetch_log=SourceFetchLog(
            results=[
                SourceFetchResult(
                    source_id="src_recent",
                    url="https://investor.targetco.example/recent",
                    status="failed",
                    failure_reason="http_403",
                )
            ]
        ),
    )

    assert "TargetCo" in report.markdown
    assert "Costco" not in report.markdown
    assert "c_supplier" in report.claim_ids
    assert "c_recent" not in report.claim_ids
    assert "c_secondary" not in report.claim_ids
    assert "src_primary" in report.source_ids
    assert "src_recent" not in report.source_ids
    assert "src_secondary" not in report.source_ids
    assert "Some discovered investor, earnings, filing, or news sources" in report.markdown


def test_supplier_meeting_fallback_requires_meeting_prep_deliverable() -> None:
    assert can_apply_supplier_meeting_fallback(_charter()) is True
    assert (
        can_apply_supplier_meeting_fallback(
            ResearchCharter(
                target="TargetCo",
                target_type="company",
                research_lens="general",
                depth="brief",
                deliverable="company_brief",
                key_questions=["What matters?"],
            )
        )
        is False
    )
