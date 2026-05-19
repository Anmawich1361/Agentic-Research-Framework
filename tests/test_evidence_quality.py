from agentic_research.evidence_quality import (
    classify_evidence_claim,
    find_near_duplicate_claims,
    normalize_claim_text,
)
from agentic_research.models import EvidenceClaim


def _claim(claim_id: str, text: str, *, claim_type: str = "fact") -> EvidenceClaim:
    return EvidenceClaim(
        id=claim_id,
        claim=text,
        claim_type=claim_type,  # type: ignore[arg-type]
        confidence="medium",
        report_section="overview",
        source_id="src_1",
        source_url="https://example.com/source",
    )


def test_normalize_claim_text_removes_punctuation_case_and_reporting_fillers() -> None:
    assert (
        normalize_claim_text("Costco states that suppliers must follow Costco's code.")
        == "costco suppliers must follow costco code"
    )


def test_find_near_duplicate_claims_catches_c1_r1_style_repeats() -> None:
    duplicates = find_near_duplicate_claims(
        [
            _claim("c1", "Costco says suppliers must comply with its vendor code of conduct."),
            _claim("r1", "Costco states that suppliers must comply with Costco's vendor code of conduct."),
            _claim("c2", "Costco operates warehouse clubs in multiple countries."),
        ]
    )

    assert len(duplicates) == 1
    assert duplicates[0].kept_claim_id == "c1"
    assert duplicates[0].duplicate_claim_id == "r1"


def test_classify_evidence_claim_identifies_metadata_and_finding_aid_claims() -> None:
    assert (
        classify_evidence_claim(
            _claim("meta", "The source page describes Costco supplier information.")
        )
        == "source_metadata_only"
    )
    assert (
        classify_evidence_claim(
            _claim("aid", "This source is useful for researching Costco suppliers.")
        )
        == "source_finding_aid"
    )


def test_classify_evidence_claim_separates_substantive_claims_from_weak_inference() -> None:
    assert (
        classify_evidence_claim(
            _claim("substantive", "Costco requires suppliers to follow its vendor code of conduct.")
        )
        == "substantive"
    )
    assert (
        classify_evidence_claim(
            _claim(
                "weak",
                "Costco likely has leverage in supplier negotiations.",
                claim_type="inference",
            )
        )
        == "weak_inference"
    )
