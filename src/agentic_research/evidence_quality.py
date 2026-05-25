from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Literal

from agentic_research.models import EvidenceClaim, StrictModel


EvidenceQualityCategory = Literal[
    "substantive",
    "source_metadata_only",
    "source_finding_aid",
    "weak_inference",
    "unsupported_or_unclear",
]

DEFAULT_NEAR_DUPLICATE_THRESHOLD = 0.86

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_REPORTING_FILLERS = {
    "according",
    "claim",
    "claims",
    "reported",
    "reports",
    "said",
    "says",
    "source",
    "sources",
    "stated",
    "states",
}
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "our",
    "that",
    "the",
    "their",
    "these",
    "this",
    "those",
    "to",
    "was",
    "were",
    "with",
}
_FILLER_TOKENS = _REPORTING_FILLERS | _STOPWORDS
_UNCLEAR_MARKERS = (
    "as fetched",
    "could not verify",
    "no filings data",
    "unclear",
    "unknown",
    "not available",
    "not enough information",
    "not retrieved",
    "not verified",
    "not specified",
    "n/a",
)
_FINDING_AID_MARKERS = (
    "can be used",
    "could be used",
    "helps research",
    "is relevant",
    "is useful",
    "recommended use",
    "recommended uses",
    "useful for researching",
)
_WEAK_INFERENCE_MARKERS = (
    "appears",
    "could",
    "indicates",
    "likely",
    "may",
    "might",
    "points to",
    "suggests",
)
_SOURCE_METADATA_RE = re.compile(
    r"\b(?:this|the)?\s*(?:source|page|website|article|report|filing|press release)"
    r"\b.*\b(?:describes|summarizes|provides|contains|covers|outlines|explains|lists)\b"
)


class NearDuplicateEvidenceClaim(StrictModel):
    kept_claim_id: str
    duplicate_claim_id: str
    similarity: float
    normalized_claim: str


class EvidenceQualityFinding(StrictModel):
    claim_id: str
    category: EvidenceQualityCategory
    reason: str
    blocking: bool = True


class EvidenceQualityReview(StrictModel):
    findings: list[EvidenceQualityFinding]
    near_duplicates: list[NearDuplicateEvidenceClaim]


def normalize_claim_text(text: str) -> str:
    normalized = text.lower().replace("'s", "")
    tokens = [
        token
        for token in _TOKEN_RE.findall(normalized)
        if token not in _FILLER_TOKENS
    ]
    return " ".join(tokens)


def _meaningful_tokens(text: str) -> set[str]:
    return set(normalize_claim_text(text).split())


def claim_similarity(left: str, right: str) -> float:
    left_normalized = normalize_claim_text(left)
    right_normalized = normalize_claim_text(right)
    if not left_normalized or not right_normalized:
        return 0.0
    sequence_score = SequenceMatcher(None, left_normalized, right_normalized).ratio()
    left_tokens = set(left_normalized.split())
    right_tokens = set(right_normalized.split())
    token_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    return max(sequence_score, token_score)


def is_near_duplicate_claim(
    left: EvidenceClaim,
    right: EvidenceClaim,
    *,
    threshold: float = DEFAULT_NEAR_DUPLICATE_THRESHOLD,
) -> bool:
    if left.id == right.id:
        return False
    return claim_similarity(left.claim, right.claim) >= threshold


def find_near_duplicate_claims(
    claims: list[EvidenceClaim],
    *,
    threshold: float = DEFAULT_NEAR_DUPLICATE_THRESHOLD,
) -> list[NearDuplicateEvidenceClaim]:
    duplicates: list[NearDuplicateEvidenceClaim] = []
    seen: list[EvidenceClaim] = []
    for claim in claims:
        duplicate_of = next(
            (
                existing
                for existing in seen
                if is_near_duplicate_claim(existing, claim, threshold=threshold)
            ),
            None,
        )
        if duplicate_of is None:
            seen.append(claim)
            continue
        duplicates.append(
            NearDuplicateEvidenceClaim(
                kept_claim_id=duplicate_of.id,
                duplicate_claim_id=claim.id,
                similarity=round(claim_similarity(duplicate_of.claim, claim.claim), 3),
                normalized_claim=normalize_claim_text(claim.claim),
            )
        )
    return duplicates


def classify_evidence_claim(claim: EvidenceClaim) -> EvidenceQualityCategory:
    raw_text = " ".join(claim.claim.lower().split())
    meaningful_tokens = _meaningful_tokens(claim.claim)

    if claim.claim_type == "fact" and not (claim.source_id or claim.source_url):
        return "unsupported_or_unclear"
    if len(meaningful_tokens) < 4 or any(marker in raw_text for marker in _UNCLEAR_MARKERS):
        return "unsupported_or_unclear"
    if any(marker in raw_text for marker in _FINDING_AID_MARKERS):
        return "source_finding_aid"
    if _SOURCE_METADATA_RE.search(raw_text):
        return "source_metadata_only"
    if claim.claim_type in {"inference", "opinion", "unknown"} or any(
        marker in raw_text for marker in _WEAK_INFERENCE_MARKERS
    ):
        return "weak_inference"
    return "substantive"


def review_evidence_quality(claims: list[EvidenceClaim]) -> EvidenceQualityReview:
    findings: list[EvidenceQualityFinding] = []
    for claim in claims:
        category = classify_evidence_claim(claim)
        if category == "substantive":
            continue
        blocking = category in {
            "source_metadata_only",
            "source_finding_aid",
            "unsupported_or_unclear",
        }
        findings.append(
            EvidenceQualityFinding(
                claim_id=claim.id,
                category=category,
                reason=_reason_for_category(category),
                blocking=blocking,
            )
        )
    return EvidenceQualityReview(
        findings=findings,
        near_duplicates=find_near_duplicate_claims(claims),
    )


def evidence_quality_validation_warnings(claims: list[EvidenceClaim]) -> list[str]:
    review = review_evidence_quality(claims)
    warnings = [
        f"{finding.claim_id}: evidence quality category {finding.category}: "
        f"{finding.reason}"
        for finding in review.findings
        if finding.blocking
    ]
    warnings.extend(
        f"{duplicate.duplicate_claim_id}: near-duplicate evidence claim repeats "
        f"{duplicate.kept_claim_id} after normalized claim comparison "
        f"(similarity {duplicate.similarity})."
        for duplicate in review.near_duplicates
    )
    return warnings


def _reason_for_category(category: EvidenceQualityCategory) -> str:
    return {
        "source_metadata_only": (
            "Claim describes the source artifact rather than a substantive fact "
            "about the research target."
        ),
        "source_finding_aid": (
            "Claim says why a source is useful instead of extracting evidence "
            "from that source."
        ),
        "weak_inference": "Claim is an inference and should remain caveated in synthesis.",
        "unsupported_or_unclear": "Claim is too unclear or lacks required source support.",
        "substantive": "Claim contains substantive evidence.",
    }[category]


__all__ = [
    "DEFAULT_NEAR_DUPLICATE_THRESHOLD",
    "EvidenceQualityCategory",
    "EvidenceQualityFinding",
    "EvidenceQualityReview",
    "NearDuplicateEvidenceClaim",
    "claim_similarity",
    "classify_evidence_claim",
    "evidence_quality_validation_warnings",
    "find_near_duplicate_claims",
    "is_near_duplicate_claim",
    "normalize_claim_text",
    "review_evidence_quality",
]
