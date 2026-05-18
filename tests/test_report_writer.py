from agentic_research.models import (
    EvidenceClaim,
    EvidenceLedger,
    ResearchCharter,
    ResearchPlan,
    SourceCandidate,
    SourceMap,
    SourceScore,
)
from agentic_research.report_writer import (
    render_mock_report,
    render_source_appendix,
    select_report_template_name,
)


def _charter(deliverable: str, lens: str = "general") -> ResearchCharter:
    return ResearchCharter(
        target="ServiceTitan",
        target_type="company",
        research_lens=lens,  # type: ignore[arg-type]
        depth="standard",
        deliverable=deliverable,
        key_questions=["What matters?"],
    )


def _source_map() -> SourceMap:
    return SourceMap(
        sources=[
            SourceCandidate(
                id="src_servicetitan_primary",
                title="ServiceTitan company overview",
                publisher="ServiceTitan",
                url="https://www.servicetitan.com/company",
                source_type="primary_company",
                bias_risk="high",
                relevance_rationale="Primary company context.",
                recommended_uses=["overview"],
                publication_date="2026-02-01",
            )
        ],
        scores=[
            SourceScore(
                source_id="src_servicetitan_primary",
                authority_score=4,
                relevance_score=5,
                recency_score=5,
                coverage_score=4,
                bias_risk="high",
                final_score=4.2,
                include=True,
            )
        ],
        gaps=[],
    )


def test_select_report_template_name_uses_lens_and_deliverable() -> None:
    assert select_report_template_name(_charter("meeting_prep_brief", "sales")) == "meeting_prep.md"
    assert select_report_template_name(_charter("investment_memo", "investment")) == "investment_memo.md"
    assert select_report_template_name(_charter("company_brief")) == "company_brief.md"


def test_render_source_appendix_uses_source_map_rows() -> None:
    appendix = render_source_appendix(_source_map())

    assert "# Source Appendix" in appendix
    assert "ServiceTitan company overview" in appendix
    assert "src_servicetitan_primary" not in appendix
    assert "4.2" in appendix


def test_render_mock_report_includes_required_phase_5_sections() -> None:
    report = render_mock_report(
        charter=_charter("company_brief"),
        plan=ResearchPlan(
            research_questions=["What does ServiceTitan do?"],
            report_sections=["overview"],
            required_source_types=["primary_company"],
            checkpoint_questions=["Which buyer persona matters?"],
        ),
        source_map=_source_map(),
        evidence_ledger=EvidenceLedger(
            claims=[
                EvidenceClaim(
                    id="claim_1",
                    claim="ServiceTitan provides software for trades businesses.",
                    claim_type="fact",
                    confidence="medium",
                    report_section="overview",
                    source_id="src_servicetitan_primary",
                    source_title="ServiceTitan company overview",
                    source_url="https://www.servicetitan.com/company",
                    source_type="primary_company",
                )
            ]
        ),
    )

    assert "## Executive Summary" in report.markdown
    assert "## Key Findings" in report.markdown
    assert "## Business Overview" in report.markdown
    assert "## Competitors" in report.markdown
    assert "## Risks" in report.markdown
    assert "## Open Questions" in report.markdown
    assert "## Source Appendix" in report.markdown
    assert report.source_ids == ["src_servicetitan_primary"]
