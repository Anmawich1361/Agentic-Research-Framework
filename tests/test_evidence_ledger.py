import pytest

from agentic_research.evidence_ledger import EvidenceLedger, raise_if_report_has_unsupported_claims
from agentic_research.models import EvidenceClaim, SourceCandidate, SourceMap, SourceScore


def _source_map() -> SourceMap:
    return SourceMap(
        sources=[
            SourceCandidate(
                id="src_primary",
                title="Primary company overview",
                publisher="ExampleCo",
                url="https://example.com/company",
                source_type="primary_company",
                bias_risk="high",
                relevance_rationale="Primary company context.",
                recommended_uses=["overview"],
            ),
            SourceCandidate(
                id="src_blog",
                title="Analyst blog",
                publisher="Example Analyst",
                url="https://example.com/blog",
                source_type="expert_blog",
                bias_risk="medium",
                relevance_rationale="Analyst context.",
                recommended_uses=["context"],
            ),
        ],
        scores=[
            SourceScore(
                source_id="src_primary",
                authority_score=4,
                relevance_score=5,
                recency_score=4,
                coverage_score=4,
                bias_risk="high",
                final_score=4.1,
                include=True,
            ),
            SourceScore(
                source_id="src_blog",
                authority_score=2,
                relevance_score=4,
                recency_score=4,
                coverage_score=3,
                bias_risk="medium",
                final_score=3.0,
                include=True,
            ),
        ],
        gaps=[],
    )


def test_evidence_ledger_lists_claims_by_section() -> None:
    ledger = EvidenceLedger()
    claim = EvidenceClaim(
        id="claim_1",
        claim="Nvidia sells accelerated computing platforms.",
        claim_type="fact",
        source_id="src_1",
        source_title="NVIDIA company overview",
        source_url="https://example.com/nvidia",
        source_type="primary_company",
        confidence="medium",
        report_section="overview",
    )

    ledger.add_claim(claim)

    assert ledger.list_claims_by_section("overview") == [claim]
    assert ledger.list_claims_by_section("risks") == []


def test_evidence_ledger_validates_fact_sources_and_authority_floor() -> None:
    ledger = EvidenceLedger()
    ledger.add_claim(
        EvidenceClaim(
            id="claim_missing_source",
            claim="Nvidia is a public company.",
            claim_type="fact",
            confidence="high",
            report_section="overview",
        )
    )
    ledger.add_claim(
        EvidenceClaim(
            id="claim_low_authority",
            claim="Nvidia has a durable advantage in AI accelerators.",
            claim_type="fact",
            source_id="src_low",
            confidence="high",
            report_section="analysis",
        )
    )

    warnings = ledger.validate(
        source_scores={
            "src_low": SourceScore(
                source_id="src_low",
                authority_score=2,
                relevance_score=4,
                recency_score=5,
                coverage_score=3,
                bias_risk="medium",
                final_score=3.1,
                include=True,
            )
        },
        high_confidence_authority_floor=4,
    )

    assert any("claim_missing_source" in warning and "source id or URL" in warning for warning in warnings)
    assert any("claim_low_authority" in warning and "low-authority" in warning for warning in warnings)


def test_evidence_ledger_detects_duplicate_claim_ids() -> None:
    claim = EvidenceClaim(
        id="claim_duplicate",
        claim="ExampleCo describes its product portfolio.",
        claim_type="fact",
        source_id="src_primary",
        source_url="https://example.com/company",
        confidence="medium",
        report_section="overview",
    )
    ledger = EvidenceLedger([claim, claim])

    warnings = ledger.validate(source_map=_source_map())

    assert any(
        "claim_duplicate" in warning
        and "duplicate evidence claim id" in warning
        and "identical claim/source content" in warning
        for warning in warnings
    )


def test_evidence_ledger_detects_conflicting_duplicate_claim_ids() -> None:
    ledger = EvidenceLedger(
        [
            EvidenceClaim(
                id="claim_conflict",
                claim="ExampleCo sells workflow software.",
                claim_type="fact",
                source_id="src_primary",
                source_url="https://example.com/company",
                confidence="medium",
                report_section="overview",
            ),
            EvidenceClaim(
                id="claim_conflict",
                claim="ExampleCo has a durable category advantage.",
                claim_type="inference",
                source_id="src_blog",
                source_url="https://example.com/blog",
                confidence="medium",
                report_section="analysis",
            ),
        ]
    )

    warnings = ledger.validate(source_map=_source_map())

    assert any(
        "claim_conflict" in warning
        and "duplicate evidence claim id" in warning
        and "conflicting claim/source content" in warning
        for warning in warnings
    )


def test_report_generation_gate_fails_on_unsupported_claims() -> None:
    ledger = EvidenceLedger(
        [
            EvidenceClaim(
                id="claim_missing_source",
                claim="ServiceTitan serves contractors.",
                claim_type="fact",
                confidence="medium",
                report_section="overview",
            )
        ]
    )
    ledger.validate()

    with pytest.raises(ValueError, match="unsupported evidence claims"):
        raise_if_report_has_unsupported_claims(ledger)


def test_evidence_ledger_validates_high_confidence_inferences_against_authority() -> None:
    ledger = EvidenceLedger(
        [
            EvidenceClaim(
                id="claim_low_authority_inference",
                claim="ServiceTitan likely has strong buyer awareness.",
                claim_type="inference",
                source_id="src_blog",
                confidence="high",
                report_section="sales_context",
            )
        ]
    )

    warnings = ledger.validate(
        source_scores={
            "src_blog": SourceScore(
                source_id="src_blog",
                authority_score=2,
                relevance_score=4,
                recency_score=5,
                coverage_score=3,
                bias_risk="medium",
                final_score=3.1,
                include=True,
            )
        }
    )

    assert any("claim_low_authority_inference" in warning for warning in warnings)


def test_evidence_ledger_warns_for_unknown_source_ids() -> None:
    ledger = EvidenceLedger(
        [
            EvidenceClaim(
                id="claim_unknown_source",
                claim="ExampleCo has a new product line.",
                claim_type="fact",
                source_id="src_unknown",
                source_url="https://example.com/unknown",
                confidence="medium",
                report_section="overview",
            )
        ]
    )

    warnings = ledger.validate(source_map=_source_map())

    assert any("claim_unknown_source" in warning and "unknown source id" in warning for warning in warnings)


def test_evidence_ledger_warns_for_mismatched_source_id_and_url() -> None:
    ledger = EvidenceLedger(
        [
            EvidenceClaim(
                id="claim_mismatched_url",
                claim="ExampleCo describes its product portfolio.",
                claim_type="fact",
                source_id="src_primary",
                source_url="https://example.com/not-the-company-page",
                confidence="medium",
                report_section="overview",
            )
        ]
    )

    warnings = ledger.validate(source_map=_source_map())

    assert any(
        "claim_mismatched_url" in warning and "does not match source map URL" in warning
        for warning in warnings
    )


def test_evidence_ledger_warns_for_high_confidence_fact_from_low_authority_source() -> None:
    ledger = EvidenceLedger(
        [
            EvidenceClaim(
                id="claim_high_confidence_low_authority",
                claim="ExampleCo has a durable category advantage.",
                claim_type="fact",
                source_id="src_blog",
                source_url="https://example.com/blog",
                confidence="high",
                report_section="analysis",
            )
        ]
    )

    warnings = ledger.validate(source_map=_source_map())

    assert any(
        "claim_high_confidence_low_authority" in warning and "low-authority" in warning
        for warning in warnings
    )
