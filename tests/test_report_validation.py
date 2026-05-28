import pytest

from agentic_research.models import (
    EvidenceClaim,
    EvidenceLedger,
    Report,
    SourceCandidate,
    SourceMap,
    SourceScore,
)
from agentic_research.report_validation import (
    ReportSectionValidationError,
    missing_report_sections,
    required_sections_for_template,
    validate_report,
    validate_report_traceability,
)


def _source_map() -> SourceMap:
    return SourceMap(
        sources=[
            SourceCandidate(
                id="src_costco_primary",
                title="Costco vendor page",
                publisher="Costco",
                url="https://example.com/vendor",
                source_type="primary_company",
                bias_risk="medium",
                relevance_rationale="Vendor context.",
                recommended_uses=["supplier meeting"],
            )
        ],
        scores=[
            SourceScore(
                source_id="src_costco_primary",
                authority_score=4,
                relevance_score=5,
                recency_score=4,
                coverage_score=4,
                bias_risk="medium",
                final_score=4.2,
                include=True,
            )
        ],
        gaps=[],
    )


def _quality_source_map() -> SourceMap:
    return SourceMap(
        sources=[
            SourceCandidate(
                id="src_primary",
                title="Costco primary source",
                publisher="Costco",
                url="https://example.com/primary",
                source_type="primary_company",
                bias_risk="medium",
                relevance_rationale="Primary company evidence.",
                recommended_uses=["stable facts"],
            ),
            SourceCandidate(
                id="src_news",
                title="Costco recent coverage",
                publisher="Example News",
                url="https://example.com/news",
                source_type="news",
                bias_risk="medium",
                relevance_rationale="Recent reporting.",
                recommended_uses=["recent developments"],
            ),
            SourceCandidate(
                id="src_quartr",
                title="Quartr Costco earnings call finder",
                publisher="Quartr",
                url="https://example.com/quartr/costco",
                source_type="source_finding_aid",
                bias_risk="medium",
                relevance_rationale="Useful for finding earnings-call materials.",
                recommended_uses=["find transcript"],
            ),
        ],
        scores=[
            SourceScore(
                source_id="src_primary",
                authority_score=4,
                relevance_score=5,
                recency_score=4,
                coverage_score=4,
                bias_risk="medium",
                final_score=4.2,
                include=True,
            ),
            SourceScore(
                source_id="src_news",
                authority_score=3,
                relevance_score=4,
                recency_score=5,
                coverage_score=3,
                bias_risk="medium",
                final_score=3.5,
                include=True,
            ),
            SourceScore(
                source_id="src_quartr",
                authority_score=2,
                relevance_score=3,
                recency_score=3,
                coverage_score=2,
                bias_risk="medium",
                final_score=2.5,
                include=True,
            ),
        ],
        gaps=[],
    )


def _short_id_source_map() -> SourceMap:
    sources = [
        SourceCandidate(
            id=source_id,
            title=f"Costco source {source_id}",
            publisher="Costco",
            url=f"https://example.com/{source_id}",
            source_type="primary_company",
            bias_risk="medium",
            relevance_rationale="Source appendix validation fixture.",
            recommended_uses=["supplier meeting"],
        )
        for source_id in ["s1", "s2", "s4"]
    ]
    return SourceMap(
        sources=sources,
        scores=[
            SourceScore(
                source_id=source.id,
                authority_score=4,
                relevance_score=5,
                recency_score=4,
                coverage_score=4,
                bias_risk="medium",
                final_score=4.2,
                include=True,
            )
            for source in sources
        ],
        gaps=[],
    )


def _ledger(claims: list[EvidenceClaim] | None = None) -> EvidenceLedger:
    return EvidenceLedger(
        claims=claims
        if claims is not None
        else [
            EvidenceClaim(
                id="claim_1",
                claim="Costco publishes vendor contact information.",
                claim_type="fact",
                source_id="src_costco_primary",
                source_url="https://example.com/vendor",
                confidence="medium",
                report_section="what_we_know",
                quote_or_excerpt="Vendor Inquiries",
            )
        ]
    )


def _short_id_source_ledger() -> EvidenceLedger:
    return EvidenceLedger(
        claims=[
            EvidenceClaim(
                id="claim_1",
                claim="Costco publishes vendor expectations.",
                claim_type="fact",
                source_id="s1",
                source_url="https://example.com/s1",
                confidence="medium",
                report_section="what_we_know",
                quote_or_excerpt="vendor expectations",
            )
        ]
    )


def _quality_ledger() -> EvidenceLedger:
    return EvidenceLedger(
        claims=[
            EvidenceClaim(
                id="c_primary",
                claim="Costco operates membership warehouse clubs.",
                claim_type="fact",
                source_id="src_primary",
                source_url="https://example.com/primary",
                confidence="medium",
                report_section="what_we_know",
                quote_or_excerpt="membership warehouse clubs",
            ),
            EvidenceClaim(
                id="c_news",
                claim="Recent reporting said Costco discussed e-commerce growth.",
                claim_type="fact",
                source_id="src_news",
                source_url="https://example.com/news",
                confidence="medium",
                report_section="recent_developments",
                quote_or_excerpt="e-commerce growth",
            ),
            EvidenceClaim(
                id="c_primary_two",
                claim="Costco files annual reports with business information.",
                claim_type="fact",
                source_id="src_primary",
                source_url="https://example.com/primary",
                confidence="medium",
                report_section="what_we_know",
                quote_or_excerpt="annual reports",
            ),
        ]
    )


def _complete_meeting_report(body: str) -> Report:
    return _report(
        "# Costco Meeting Prep\n\n"
        "## Executive Summary\n"
        "Costco operates membership warehouse clubs. [c_primary]\n\n"
        "## Context for Meeting\n"
        "This brief supports a supplier meeting; category and team are unknown.\n\n"
        "## What We Know\n"
        "- Costco operates membership warehouse clubs. [c_primary]\n"
        "- Costco files annual reports with business information. [c_primary_two]\n\n"
        "## What We Do Not Know\n"
        "- Recent earnings/transcript support was not verified from available sources.\n\n"
        f"{body}\n\n"
        "## Questions to Ask\n"
        "- Which buying team owns this category?\n\n"
        "## Risks and Watchouts\n"
        "- Category-specific requirements are not verified from available sources.\n\n"
        "## Source Appendix\n"
        "- src_primary — Costco primary source — https://example.com/primary\n"
        "- src_news — Costco recent coverage — https://example.com/news\n",
        source_ids=["src_primary", "src_news"],
    )


def _ledger_with_claim_ids(claim_ids: list[str]) -> EvidenceLedger:
    return EvidenceLedger(
        claims=[
            EvidenceClaim(
                id=claim_id,
                claim=f"Costco evidence claim {claim_id}.",
                claim_type="fact",
                source_id="src_costco_primary",
                source_url="https://example.com/vendor",
                confidence="medium",
                report_section="what_we_know",
            )
            for claim_id in claim_ids
        ]
    )


def _report(markdown: str, *, source_ids: list[str] | None = None) -> Report:
    return Report(
        title="Costco Meeting Prep",
        markdown=markdown,
        source_ids=source_ids or ["src_costco_primary"],
    )


def test_required_sections_are_template_specific() -> None:
    assert required_sections_for_template("meeting_prep.md") == [
        "Executive Summary",
        "Context for Meeting",
        "What We Know",
        "What We Do Not Know",
        "Supplier/Buyer Angle",
        "Questions to Ask",
        "Risks and Watchouts",
        "Source Appendix",
    ]
    assert "Value Chain" in required_sections_for_template("industry_primer.md")
    assert "Competitive Landscape" in required_sections_for_template("company_brief.md")


def test_meeting_prep_requires_what_we_do_not_know() -> None:
    report = _report(
        "# Costco Meeting Prep\n\n"
        "## Executive Summary\nSummary.\n\n"
        "## Context for Meeting\nContext.\n\n"
        "## What We Know\nFact. [claim_1]\n\n"
        "## Supplier/Buyer Angle\nAngle.\n\n"
        "## Questions to Ask\nQuestions.\n\n"
        "## Risks and Watchouts\nRisks.\n\n"
        "## Source Appendix\n- Costco vendor page (src_costco_primary)\n"
    )

    missing = missing_report_sections(
        report,
        template_name="meeting_prep.md",
    )

    assert missing == ["What We Do Not Know"]


def test_thin_evidence_requires_evidence_limitations_section() -> None:
    report = _report(
        "# Costco Meeting Prep\n\n"
        "## Executive Summary\nSummary.\n\n"
        "## Context for Meeting\nContext.\n\n"
        "## What We Know\nFact. [claim_1]\n\n"
        "## What We Do Not Know\nUnknowns.\n\n"
        "## Supplier/Buyer Angle\nAngle.\n\n"
        "## Questions to Ask\nQuestions.\n\n"
        "## Risks and Watchouts\nRisks.\n\n"
        "## Source Appendix\n- Costco vendor page (src_costco_primary)\n"
    )

    issues = validate_report(
        report,
        evidence_ledger=_ledger(),
        source_map=_source_map(),
        template_name="meeting_prep.md",
    ).issues

    assert any(
        issue.category == "source_gap"
        and "Evidence Limitations" in issue.problem
        for issue in issues
    )


def test_uncited_generic_broad_claim_is_flagged() -> None:
    report = _report(
        "# Costco Meeting Prep\n\n"
        "## Executive Summary\nCostco has a durable supplier advantage.\n\n"
        "## Context for Meeting\nContext.\n\n"
        "## What We Know\nFact. [claim_1]\n\n"
        "## What We Do Not Know\nUnknowns.\n\n"
        "## Supplier/Buyer Angle\nAngle.\n\n"
        "## Questions to Ask\nQuestions.\n\n"
        "## Risks and Watchouts\nRisks.\n\n"
        "## Evidence Limitations\nOnly one source supports this brief.\n\n"
        "## Source Appendix\n- Costco vendor page (src_costco_primary)\n"
    )

    issues = validate_report(
        report,
        evidence_ledger=_ledger(),
        source_map=_source_map(),
        template_name="meeting_prep.md",
    ).issues

    assert any(
        issue.severity == "high"
        and issue.category == "unsupported_claim"
        and "durable supplier advantage" in issue.problem
        for issue in issues
    )


def test_traceability_rejects_unknown_claim_and_source_references() -> None:
    report = _report(
        "# Draft\n\n## Executive Summary\nUnsupported. [claim_missing]\n",
        source_ids=["src_missing"],
    )

    with pytest.raises(ReportSectionValidationError, match="unknown evidence claim"):
        validate_report_traceability(
            report,
            evidence_ledger=_ledger(),
            source_map=_source_map(),
        )


def test_traceability_allows_short_source_ids_in_source_appendix() -> None:
    report = _report(
        "# Draft\n\n"
        "## Executive Summary\n"
        "Costco publishes vendor expectations. [claim_1]\n\n"
        "## Source Appendix\n"
        "- [s1] Costco source s1 — https://example.com/s1\n"
        "- [s2] Costco source s2 — https://example.com/s2\n"
        "- [s4] Costco source s4 — https://example.com/s4\n",
        source_ids=["s1", "s2", "s4"],
    )

    validate_report_traceability(
        report,
        evidence_ledger=_short_id_source_ledger(),
        source_map=_short_id_source_map(),
    )

    assert report.claim_ids == ["claim_1"]


def test_traceability_rejects_stale_short_markdown_claim_ids() -> None:
    report = _report(
        "# Draft\n\n"
        "## Executive Summary\n"
        "Costco operates internationally. [r1]\n",
        source_ids=["src_costco_primary"],
    )

    with pytest.raises(ReportSectionValidationError, match="r1"):
        validate_report_traceability(
            report,
            evidence_ledger=_ledger_with_claim_ids(["c1", "c2"]),
            source_map=_source_map(),
        )


def test_traceability_rejects_unknown_short_source_id_in_source_appendix() -> None:
    report = _report(
        "# Draft\n\n"
        "## Executive Summary\n"
        "Costco publishes vendor expectations. [claim_1]\n\n"
        "## Source Appendix\n"
        "- [s999] Unknown source — https://example.com/s999\n",
        source_ids=["s1"],
    )

    with pytest.raises(ReportSectionValidationError, match="unknown source.*s999"):
        validate_report_traceability(
            report,
            evidence_ledger=_short_id_source_ledger(),
            source_map=_short_id_source_map(),
        )


def test_unsupported_recent_development_claim_is_flagged() -> None:
    report = _complete_meeting_report(
        "## Supplier/Buyer Angle\n"
        "Recent developments show Costco is shifting supplier strategy toward digital fulfillment."
    )

    issues = validate_report(
        report,
        evidence_ledger=_quality_ledger(),
        source_map=_quality_source_map(),
        template_name="meeting_prep.md",
    ).issues

    assert any(
        issue.severity == "high"
        and issue.category == "missing_recent_signal"
        and "Recent developments" in issue.problem
        for issue in issues
    )


def test_recent_evidence_gap_caveat_is_allowed_to_proceed_to_qa() -> None:
    report = _complete_meeting_report(
        "## Supplier/Buyer Angle\n"
        "Caveat: category-specific supplier criteria and recent earnings/transcript "
        "support were not verified from available sources, so treat supplier "
        "talking points as questions to confirm."
    )

    issues = validate_report(
        report,
        evidence_ledger=_quality_ledger(),
        source_map=_quality_source_map(),
        template_name="meeting_prep.md",
    ).issues

    assert issues == []


def test_uncaveated_recent_claim_requires_dated_direct_source() -> None:
    report = _complete_meeting_report(
        "## Supplier/Buyer Angle\n"
        "Costco's recent e-commerce growth should shape supplier questions. [c_news]"
    )

    issues = validate_report(
        report,
        evidence_ledger=_quality_ledger(),
        source_map=_quality_source_map(),
        template_name="meeting_prep.md",
    ).issues

    assert not any(issue.category == "missing_recent_signal" for issue in issues)
    assert any(
        issue.severity == "medium"
        and issue.category == "stale_or_unclear_recency"
        and "publication date" in issue.problem
        for issue in issues
    )


def test_source_finding_aid_claims_are_not_promoted_to_strategy() -> None:
    ledger = _quality_ledger().model_copy(
        update={
            "claims": [
                *_quality_ledger().claims,
                EvidenceClaim(
                    id="c_aid",
                    claim="The Quartr page is useful for finding Costco earnings calls.",
                    claim_type="fact",
                    source_id="src_quartr",
                    source_url="https://example.com/quartr/costco",
                    confidence="medium",
                    report_section="recent_developments",
                    quote_or_excerpt="earnings calls",
                ),
            ]
        }
    )
    report = _complete_meeting_report(
        "## Supplier/Buyer Angle\n"
        "Costco's current strategy centers on digital fulfillment and supplier readiness. [c_aid]"
    )

    issues = validate_report(
        report,
        evidence_ledger=ledger,
        source_map=_quality_source_map(),
        template_name="meeting_prep.md",
    ).issues

    assert any(
        issue.category == "weak_source"
        and "source-finding aid" in issue.problem
        for issue in issues
    )


def test_meeting_prep_recommendations_require_citation_or_caveat() -> None:
    report = _complete_meeting_report(
        "## Supplier/Buyer Angle\n"
        "Suppliers should emphasize pack architecture and landed-cost discipline."
    )

    issues = validate_report(
        report,
        evidence_ledger=_quality_ledger(),
        source_map=_quality_source_map(),
        template_name="meeting_prep.md",
    ).issues

    assert any(
        issue.category == "overconfident_inference"
        and "supplier-meeting recommendation" in issue.problem
        for issue in issues
    )
