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
