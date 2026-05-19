from agentic_research.models import (
    EvidenceClaim,
    EvidenceLedger,
    Report,
    SourceCandidate,
    SourceMap,
    SourceScore,
)
from agentic_research.qa import run_deterministic_qa_checks


def test_deterministic_qa_warns_for_missing_report_sections() -> None:
    review = run_deterministic_qa_checks(
        source_map=SourceMap(sources=[], scores=[], gaps=[]),
        evidence_ledger=EvidenceLedger(claims=[]),
        draft_report=Report(
            title="Draft",
            markdown="# Draft\n\n## Executive Summary\nOnly summary.",
            source_ids=[],
        ),
    )

    problems = [issue.problem for issue in review.issues]
    assert "Report is missing a source appendix section." in problems
    assert "Report is missing a risks section." in problems
    assert "Report is missing an open questions section." in problems
    assert {issue.severity for issue in review.issues} == {"medium"}
    assert review.ready_to_publish is False


def test_deterministic_qa_flags_unsupported_and_low_authority_claims() -> None:
    review = run_deterministic_qa_checks(
        source_map=SourceMap(
            sources=[
                SourceCandidate(
                    id="src_blog",
                    title="Blog",
                    publisher="Example",
                    url="https://example.com/blog",
                    source_type="expert_blog",
                    bias_risk="medium",
                    relevance_rationale="Context.",
                    recommended_uses=["context"],
                )
            ],
            scores=[
                SourceScore(
                    source_id="src_blog",
                    authority_score=2,
                    relevance_score=4,
                    recency_score=4,
                    coverage_score=3,
                    bias_risk="medium",
                    final_score=3.0,
                    include=True,
                )
            ],
            gaps=[],
        ),
        evidence_ledger=EvidenceLedger(
            claims=[
                EvidenceClaim(
                    id="claim_missing_source",
                    claim="Salesforce has durable pricing power.",
                    claim_type="fact",
                    confidence="medium",
                    report_section="key_findings",
                ),
                EvidenceClaim(
                    id="claim_low_authority",
                    claim="Salesforce likely has strong buyer awareness.",
                    claim_type="inference",
                    source_id="src_blog",
                    confidence="high",
                    report_section="key_findings",
                ),
            ]
        ),
        draft_report=Report(
            title="Draft",
            markdown=(
                "# Draft\n\n"
                "## Executive Summary\nSummary.\n\n"
                "## Key Findings\nFinding.\n\n"
                "## Business Overview\nOverview.\n\n"
                "## Competitors\nCompetitors.\n\n"
                "## Risks\nRisks.\n\n"
                "## Open Questions\nQuestions.\n\n"
                "## Source Appendix\nSources."
            ),
            source_ids=["src_blog"],
        ),
    )

    high_issues = [issue for issue in review.issues if issue.severity == "high"]
    assert any("claim_missing_source" in issue.problem for issue in high_issues)
    assert any("claim_low_authority" in issue.problem for issue in high_issues)
    assert any(issue.category == "unsupported_claim" for issue in high_issues)
    assert any(issue.category == "weak_source" for issue in high_issues)
    assert review.ready_to_publish is False


def test_deterministic_qa_flags_uncited_broad_report_claims() -> None:
    review = run_deterministic_qa_checks(
        source_map=SourceMap(sources=[], scores=[], gaps=[]),
        evidence_ledger=EvidenceLedger(claims=[]),
        draft_report=Report(
            title="Draft",
            markdown=(
                "# Draft\n\n"
                "## Executive Summary\n"
                "Costco has a durable supplier advantage in its category.\n\n"
                "## Key Findings\nNo claims.\n\n"
                "## Business Overview\nOverview.\n\n"
                "## Competitors\nCompetitors.\n\n"
                "## Risks\nRisks.\n\n"
                "## Open Questions\nQuestions.\n\n"
                "## Source Appendix\nSources."
            ),
            source_ids=[],
        ),
    )

    assert any(
        issue.severity == "high"
        and issue.category == "unsupported_claim"
        and "durable supplier advantage" in issue.problem
        for issue in review.issues
    )
    assert review.ready_to_publish is False
