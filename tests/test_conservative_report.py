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
from agentic_research.qa import has_high_severity_issues, run_deterministic_qa_checks
from agentic_research.report_writer import select_report_template_name


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


def test_conservative_report_handles_investment_meeting_context() -> None:
    charter = ResearchCharter(
        target="ATS Corporation",
        target_type="company",
        research_lens="investment",
        depth="standard",
        deliverable="Pre-meeting investment research brief",
        key_questions=["What should we ask management?"],
    )
    source_map = SourceMap(
        sources=[
            SourceCandidate(
                id="src_current",
                title="ATS fiscal 2026 Q4 results",
                publisher="ATS",
                url="https://example.com/q4",
                source_type="corporate_filing",
                publication_date="2026-05-28",
                relevance_rationale="Latest results.",
                recommended_uses=["recent operating metrics"],
                bias_risk="low",
            ),
            SourceCandidate(
                id="src_transcript",
                title="ATS Q4 transcript",
                publisher="Transcript Site",
                url="https://example.com/transcript",
                source_type="earnings_transcript",
                publication_date="2026-05-29",
                relevance_rationale="Management commentary.",
                recommended_uses=["management commentary"],
                bias_risk="medium",
            ),
        ],
        scores=[
            SourceScore(
                source_id="src_current",
                authority_score=5,
                relevance_score=5,
                recency_score=5,
                coverage_score=4,
                bias_risk="low",
                final_score=4.8,
                include=True,
            ),
            SourceScore(
                source_id="src_transcript",
                authority_score=3,
                relevance_score=4,
                recency_score=5,
                coverage_score=3,
                bias_risk="medium",
                final_score=3.6,
                include=True,
            ),
        ],
        gaps=[
            "Consensus estimates and valuation data were not found.",
            "The exact latest quarter/earnings call materials should be added once located.",
        ],
    )
    report = create_conservative_report(
        charter=charter,
        plan=_plan(),
        source_map=source_map,
        evidence_ledger=EvidenceLedger(
            claims=[
                EvidenceClaim(
                    id="c_metric",
                    claim=(
                        "ATS reported fourth-quarter fiscal 2026 revenues of "
                        "$747.1 million and adjusted EBITDA of $102.5 million."
                    ),
                    claim_type="fact",
                    source_id="src_current",
                    source_url="https://example.com/q4",
                    source_type="corporate_filing",
                    confidence="high",
                    report_section="Recent financial performance",
                    quote_or_excerpt="Revenues were $747.1 million",
                ),
                EvidenceClaim(
                    id="c_visibility",
                    claim="ATS said its backlog provides solid revenue visibility into fiscal 2027.",
                    claim_type="fact",
                    source_id="src_current",
                    source_url="https://example.com/q4",
                    source_type="corporate_filing",
                    confidence="high",
                    report_section="Growth drivers",
                    quote_or_excerpt="solid revenue visibility",
                ),
                EvidenceClaim(
                    id="c_risk",
                    claim="ATS said large-program timing can affect quarterly performance.",
                    claim_type="fact",
                    source_id="src_current",
                    source_url="https://example.com/q4",
                    source_type="corporate_filing",
                    confidence="high",
                    report_section="Risks",
                    quote_or_excerpt="large-program timing",
                ),
                EvidenceClaim(
                    id="c_transcript",
                    claim="The transcript says management sounded optimistic.",
                    claim_type="fact",
                    source_id="src_transcript",
                    source_url="https://example.com/transcript",
                    source_type="earnings_transcript",
                    confidence="medium",
                    report_section="Management commentary",
                    quote_or_excerpt="optimistic",
                ),
            ]
        ),
        source_fetch_log=SourceFetchLog(
            results=[
                SourceFetchResult(source_id="src_current", url="https://example.com/q4", status="fetched"),
                SourceFetchResult(
                    source_id="src_transcript",
                    url="https://example.com/transcript",
                    status="fetched",
                ),
            ]
        ),
    )

    assert "filing-backed preliminary investment meeting brief" in report.markdown
    assert "supplier-meeting" not in report.markdown
    assert "category-specific buying criteria" not in report.markdown
    assert "latest quarter/earnings call materials should be added" not in report.markdown
    assert "c_metric" in report.claim_ids
    assert "c_risk" in report.claim_ids
    assert "c_visibility" not in report.claim_ids
    assert "c_transcript" not in report.claim_ids
    assert report.source_ids == ["src_current"]

    review = run_deterministic_qa_checks(
        source_map=source_map,
        evidence_ledger=EvidenceLedger(
            claims=[
                EvidenceClaim(
                    id="c_metric",
                    claim=(
                        "ATS reported fourth-quarter fiscal 2026 revenues of "
                        "$747.1 million and adjusted EBITDA of $102.5 million."
                    ),
                    claim_type="fact",
                    source_id="src_current",
                    source_url="https://example.com/q4",
                    source_type="corporate_filing",
                    confidence="high",
                    report_section="Recent financial performance",
                    quote_or_excerpt="Revenues were $747.1 million",
                ),
                EvidenceClaim(
                    id="c_risk",
                    claim="ATS said large-program timing can affect quarterly performance.",
                    claim_type="fact",
                    source_id="src_current",
                    source_url="https://example.com/q4",
                    source_type="corporate_filing",
                    confidence="high",
                    report_section="Risks",
                    quote_or_excerpt="large-program timing",
                ),
            ]
        ),
        draft_report=report,
        template_name=select_report_template_name(charter),
    )
    assert has_high_severity_issues(review) is False


def test_investment_meeting_conservative_report_prioritizes_dated_metrics_without_fixed_year() -> None:
    charter = ResearchCharter(
        target="ATS Corporation",
        target_type="company",
        research_lens="investment",
        depth="standard",
        deliverable="Pre-meeting investment research brief",
        key_questions=["What should we ask management?"],
    )
    source_map = SourceMap(
        sources=[
            SourceCandidate(
                id="src_current",
                title="ATS fiscal 2027 results",
                publisher="ATS",
                url="https://example.com/q4",
                source_type="corporate_filing",
                publication_date="2027-05-28",
                relevance_rationale="Latest results.",
                recommended_uses=["recent operating metrics"],
                bias_risk="low",
            )
        ],
        scores=[
            SourceScore(
                source_id="src_current",
                authority_score=5,
                relevance_score=5,
                recency_score=5,
                coverage_score=4,
                bias_risk="low",
                final_score=4.8,
                include=True,
            )
        ],
        gaps=["The exact latest quarter/earnings call materials should be added once located."],
    )
    report = create_conservative_report(
        charter=charter,
        plan=_plan(),
        source_map=source_map,
        evidence_ledger=EvidenceLedger(
            claims=[
                EvidenceClaim(
                    id="c_risk",
                    claim="ATS said large-program timing can affect quarterly performance.",
                    claim_type="fact",
                    source_id="src_current",
                    source_url="https://example.com/q4",
                    source_type="corporate_filing",
                    confidence="high",
                    report_section="Risks",
                    quote_or_excerpt="large-program timing",
                ),
                EvidenceClaim(
                    id="c_metric",
                    claim=(
                        "ATS reported fiscal 2027 revenues of $747.1 million "
                        "and adjusted EBITDA of $102.5 million."
                    ),
                    claim_type="fact",
                    source_id="src_current",
                    source_url="https://example.com/q4",
                    source_type="corporate_filing",
                    confidence="high",
                    report_section="Recent financial performance",
                    quote_or_excerpt="Revenues were $747.1 million",
                ),
            ]
        ),
        source_fetch_log=SourceFetchLog(
            results=[SourceFetchResult(source_id="src_current", url="https://example.com/q4", status="fetched")]
        ),
    )

    assert report.claim_ids[:2] == ["c_metric", "c_risk"]
    assert "latest quarter/earnings call materials should be added" not in report.markdown


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
