from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from agentic_research.evidence_ledger import (
    EvidenceLedger,
    evidence_claim_content_key,
)
from agentic_research.evidence_quality import DEFAULT_NEAR_DUPLICATE_THRESHOLD
from agentic_research.evidence_quality import claim_similarity
from agentic_research.evidence_quality import classify_evidence_claim
from agentic_research.evidence_quality import is_near_duplicate_claim
from agentic_research.models import (
    EvidenceClaim,
    EvidenceLedger as EvidenceLedgerModel,
    ResearchCharter,
    SourceCandidate,
    SourceFetchLog,
    SourceFetchResult,
    SourceMap,
    SpecialistAnalysis,
)
from agentic_research.run_artifacts import EMPTY_EVIDENCE_WARNING


_DIRECT_COMPANY_EVIDENCE_SOURCE_TYPES = {
    "corporate_filing",
    "earnings_release",
    "investor_material",
    "primary_company",
    "earnings_transcript",
}

DIRECT_EVIDENCE_SUFFICIENCY_WARNING = (
    "No direct company, filing, investor, or earnings evidence claims remained "
    "after filtering; fetched source content is too indirect for a source-grounded "
    "company report."
)


def _source_scores_by_id(source_map: SourceMap) -> dict[str, Any]:
    return {score.source_id: score for score in source_map.scores}


def _sec_archive_document_identity(url: str | None) -> tuple[str, str] | None:
    if not url:
        return None
    parsed = urlparse(url)
    if not parsed.netloc.lower().endswith("sec.gov"):
        return None
    match = re.search(
        r"/Archives/edgar/data/(\d+)/\d+/([^/?#]+)$",
        parsed.path,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    return str(int(match.group(1))), match.group(2).lower()


def _is_repairable_stale_source_url(
    *,
    claim_url: str | None,
    source_url: str,
) -> bool:
    if not claim_url:
        return True
    if _normalized_url(claim_url) == _normalized_url(source_url):
        return True
    claim_sec_identity = _sec_archive_document_identity(claim_url)
    source_sec_identity = _sec_archive_document_identity(source_url)
    return (
        claim_sec_identity is not None
        and source_sec_identity is not None
        and claim_sec_identity == source_sec_identity
    )


def _normalized_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(fragment="").geturl().rstrip("/")


def _normalize_claim_source_urls_for_source_map(
    claims: list[EvidenceClaim],
    *,
    source_map: SourceMap,
) -> tuple[list[EvidenceClaim], list[str]]:
    source_lookup = {source.id: source for source in source_map.sources}
    normalized_claims: list[EvidenceClaim] = []
    warnings: list[str] = []

    for claim in claims:
        source = source_lookup.get(claim.source_id) if claim.source_id else None
        source_url = source.url.strip() if source is not None else ""
        if not source_url or not _is_repairable_stale_source_url(
            claim_url=claim.source_url,
            source_url=source_url,
        ):
            normalized_claims.append(claim)
            continue

        if claim.source_url != source_url:
            if claim.source_url:
                warnings.append(
                    "Repaired stale source_url for evidence claim ID "
                    f"{claim.id}: replaced {claim.source_url} with final "
                    f"source_map URL {source_url}."
                )
            normalized_claims.append(claim.model_copy(update={"source_url": source_url}))
            continue

        normalized_claims.append(claim)

    return normalized_claims, warnings


def _normalize_specialist_claim_source_urls_for_source_map(
    specialist_analyses: list[SpecialistAnalysis],
    *,
    source_map: SourceMap,
) -> tuple[list[SpecialistAnalysis], list[str]]:
    normalized_analyses: list[SpecialistAnalysis] = []
    warnings: list[str] = []
    for analysis in specialist_analyses:
        normalized_claims, claim_warnings = _normalize_claim_source_urls_for_source_map(
            analysis.evidence_claims,
            source_map=source_map,
        )
        warnings.extend(claim_warnings)
        normalized_analyses.append(
            analysis.model_copy(update={"evidence_claims": normalized_claims})
        )
    return normalized_analyses, warnings


def _failed_source_metadata_claim(claim: EvidenceClaim) -> bool:
    raw_text = " ".join(claim.claim.lower().split())
    metadata_markers = (
        "page indicates",
        "page suggests",
        "source indicates",
        "source suggests",
        "website indicates",
        "website suggests",
        "materials indicate",
        "materials suggest",
        "program suggests",
    )
    if any(marker in raw_text for marker in metadata_markers):
        return True
    sensitive_topics = ("supplier", "strategy", "recent development", "recent performance")
    weak_metadata_verbs = ("indicates", "suggests", "appears", "points to")
    return any(topic in raw_text for topic in sensitive_topics) and any(
        verb in raw_text for verb in weak_metadata_verbs
    )


def _claim_id_part(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    return normalized or "claim"


def _next_specialist_claim_id(
    *,
    specialist: str,
    original_id: str,
    used_ids: set[str],
) -> str:
    prefix = _claim_id_part(specialist).lower()
    claim_part = _claim_id_part(original_id)
    candidate = f"specialist_{prefix}_{claim_part}"
    suffix = 2
    while candidate in used_ids:
        candidate = f"specialist_{prefix}_{claim_part}_{suffix}"
        suffix += 1
    return candidate


def _is_specialist_merge_near_duplicate(
    existing_claim: EvidenceClaim,
    claim: EvidenceClaim,
) -> bool:
    if is_near_duplicate_claim(existing_claim, claim):
        return True
    return (
        existing_claim.id == claim.id
        and claim_similarity(existing_claim.claim, claim.claim)
        >= DEFAULT_NEAR_DUPLICATE_THRESHOLD
    )


def _deduplicate_claims(
    base_claims: list[EvidenceClaim],
    specialist_analyses: list[SpecialistAnalysis] | None = None,
) -> tuple[list[EvidenceClaim], list[str]]:
    deduped_claims: list[EvidenceClaim] = []
    warnings: list[str] = []
    used_ids: set[str] = set()
    first_content_by_id: dict[str, tuple[str, ...]] = {}

    claims_with_origin: list[tuple[EvidenceClaim, str | None]] = [
        (claim, None) for claim in base_claims
    ]
    for analysis in specialist_analyses or []:
        claims_with_origin.extend(
            (claim, analysis.specialist) for claim in analysis.evidence_claims
        )

    for claim, specialist in claims_with_origin:
        content_key = evidence_claim_content_key(claim)
        first_content_key = first_content_by_id.get(claim.id)
        if first_content_key is None:
            near_duplicate_of = next(
                (
                    existing_claim
                    for existing_claim in deduped_claims
                    if _is_specialist_merge_near_duplicate(existing_claim, claim)
                ),
                None,
            )
            if near_duplicate_of is not None:
                warnings.append(
                    "Deduplicated near-duplicate evidence claim ID "
                    f"{claim.id}: preserved {near_duplicate_of.id} and dropped "
                    "a later claim with materially equivalent normalized text."
                )
                continue
            deduped_claims.append(claim)
            used_ids.add(claim.id)
            first_content_by_id[claim.id] = content_key
            continue

        if content_key == first_content_key:
            warnings.append(
                f"Deduplicated duplicate evidence claim ID {claim.id}: preserved "
                "the first occurrence and dropped a later identical claim."
            )
            continue

        if specialist is not None:
            near_duplicate_of = next(
                (
                    existing_claim
                    for existing_claim in deduped_claims
                    if _is_specialist_merge_near_duplicate(existing_claim, claim)
                ),
                None,
            )
            if near_duplicate_of is not None:
                warnings.append(
                    "Deduplicated near-duplicate evidence claim ID "
                    f"{claim.id}: preserved {near_duplicate_of.id} and dropped "
                    "a later claim with materially equivalent normalized text."
                )
                continue
            new_id = _next_specialist_claim_id(
                specialist=specialist,
                original_id=claim.id,
                used_ids=used_ids,
            )
            deduped_claims.append(claim.model_copy(update={"id": new_id}))
            used_ids.add(new_id)
            first_content_by_id[new_id] = content_key
            warnings.append(
                f"Renamed conflicting specialist evidence claim ID {claim.id} "
                f"to {new_id}: claim/source content differed from the first "
                "occurrence."
            )
            continue

        warnings.append(
            f"Conflicting duplicate evidence claim ID {claim.id}: claim/source "
            "content differs from the first occurrence; preserved the first "
            "occurrence and blocked synthesis until unique IDs are supplied."
        )

    return deduped_claims, warnings


def _sanitize_evidence_claims_for_synthesis(
    claims: list[EvidenceClaim],
    *,
    source_map: SourceMap,
    source_fetch_log: SourceFetchLog | None = None,
    high_confidence_authority_floor: float = 4,
) -> tuple[list[EvidenceClaim], list[str]]:
    source_lookup = {source.id: source for source in source_map.sources}
    score_lookup = _source_scores_by_id(source_map)
    fetch_result_lookup = {
        result.source_id: result
        for result in (source_fetch_log.results if source_fetch_log is not None else [])
    }
    fetch_result_by_url: dict[str, SourceFetchResult] = {}
    for result in source_fetch_log.results if source_fetch_log is not None else []:
        for url in (result.url, result.fetched_url):
            normalized_url = _normalized_url(url) if url else ""
            if normalized_url:
                fetch_result_by_url[normalized_url] = result
    sanitized_claims: list[EvidenceClaim] = []
    warnings: list[str] = []

    for claim in claims:
        source = source_lookup.get(claim.source_id) if claim.source_id else None
        has_claim_source_url = bool((claim.source_url or "").strip())
        has_source_map_url = source is not None and bool(source.url.strip())

        if not has_claim_source_url and not has_source_map_url:
            if not claim.source_id:
                warnings.append(
                    "Dropped unsupported evidence claim ID "
                    f"{claim.id} before synthesis: missing source id and source URL."
                )
                continue
            if source is not None:
                warnings.append(
                    "Dropped unsupported evidence claim ID "
                    f"{claim.id} before synthesis: source {claim.source_id} "
                    "has no usable URL."
                )
                continue

        fetch_result = fetch_result_lookup.get(claim.source_id) if claim.source_id else None
        if fetch_result is None and claim.source_url:
            fetch_result = fetch_result_by_url.get(_normalized_url(claim.source_url))
        if fetch_result is not None and fetch_result.status in {"failed", "skipped"}:
            source_label = claim.source_id or claim.source_url or fetch_result.source_id
            warnings.append(
                "Dropped unsupported evidence claim ID "
                f"{claim.id} before synthesis: source {source_label} "
                f"fetch status {fetch_result.status} produced no usable source text."
            )
            continue
        if fetch_result is not None and fetch_result.status == "fallback":
            source_label = claim.source_id or claim.source_url or fetch_result.source_id
            fallback_reason = (
                "weak fallback metadata/search-snippet context"
                if _failed_source_metadata_claim(claim)
                else "weak fallback context"
            )
            warnings.append(
                "Dropped unsupported evidence claim ID "
                f"{claim.id} before synthesis: source {source_label} only had "
                f"{fallback_reason}, not fetched source text."
            )
            continue

        quality_category = classify_evidence_claim(claim)
        if quality_category in {
            "source_metadata_only",
            "source_finding_aid",
            "unsupported_or_unclear",
        }:
            warnings.append(
                "Dropped unsupported evidence claim ID "
                f"{claim.id} before synthesis: evidence quality category "
                f"{quality_category}."
            )
            continue

        score = score_lookup.get(claim.source_id) if claim.source_id else None
        if (
            claim.confidence == "high"
            and score is not None
            and score.authority_score < high_confidence_authority_floor
        ):
            sanitized_claims.append(claim.model_copy(update={"confidence": "medium"}))
            warnings.append(
                "Downgraded evidence claim ID "
                f"{claim.id} from high to medium confidence before synthesis: "
                f"source {score.source_id} authority is {score.authority_score}."
            )
            continue

        sanitized_claims.append(claim)

    return sanitized_claims, warnings


def _validate_evidence(
    claims: list[EvidenceClaim],
    *,
    source_map: SourceMap,
    source_fetch_log: SourceFetchLog | None = None,
) -> EvidenceLedgerModel:
    normalized_claims, normalization_warnings = _normalize_claim_source_urls_for_source_map(
        claims,
        source_map=source_map,
    )
    deduped_claims, dedupe_warnings = _deduplicate_claims(normalized_claims)
    sanitized_claims, sanitization_warnings = _sanitize_evidence_claims_for_synthesis(
        deduped_claims,
        source_map=source_map,
        source_fetch_log=source_fetch_log,
    )
    ledger = EvidenceLedger(sanitized_claims)
    ledger.validate(source_scores=_source_scores_by_id(source_map), source_map=source_map)
    sufficiency_warnings = [] if ledger.claims else [EMPTY_EVIDENCE_WARNING]
    ledger.validation_warnings = [
        *normalization_warnings,
        *dedupe_warnings,
        *sanitization_warnings,
        *sufficiency_warnings,
        *ledger.validation_warnings,
    ]
    return ledger.to_model()


def _merge_specialist_claims(
    evidence_ledger: EvidenceLedgerModel,
    specialist_analyses: list[SpecialistAnalysis],
    *,
    source_map: SourceMap,
    source_fetch_log: SourceFetchLog | None = None,
) -> EvidenceLedgerModel:
    if not any(analysis.evidence_claims for analysis in specialist_analyses):
        return evidence_ledger
    normalized_base_claims, base_normalization_warnings = (
        _normalize_claim_source_urls_for_source_map(
            evidence_ledger.claims,
            source_map=source_map,
        )
    )
    normalized_specialist_analyses, specialist_normalization_warnings = (
        _normalize_specialist_claim_source_urls_for_source_map(
            specialist_analyses,
            source_map=source_map,
        )
    )
    deduped_claims, dedupe_warnings = _deduplicate_claims(
        normalized_base_claims,
        normalized_specialist_analyses,
    )
    sanitized_claims, sanitization_warnings = _sanitize_evidence_claims_for_synthesis(
        deduped_claims,
        source_map=source_map,
        source_fetch_log=source_fetch_log,
    )
    existing_warnings = list(evidence_ledger.validation_warnings)
    ledger = EvidenceLedger(sanitized_claims)
    ledger.validate(source_scores=_source_scores_by_id(source_map), source_map=source_map)
    ledger.validation_warnings = [
        *existing_warnings,
        *base_normalization_warnings,
        *specialist_normalization_warnings,
        *dedupe_warnings,
        *sanitization_warnings,
        *ledger.validation_warnings,
    ]
    return ledger.to_model()


def _is_direct_company_evidence_claim(
    claim: EvidenceClaim,
    *,
    source_lookup: dict[str, SourceCandidate],
) -> bool:
    source = source_lookup.get(claim.source_id or "")
    source_type = (claim.source_type or (source.source_type if source else "")).lower()
    return claim.claim_type == "fact" and source_type in _DIRECT_COMPANY_EVIDENCE_SOURCE_TYPES


def _direct_company_evidence_claims(
    evidence_ledger: EvidenceLedgerModel,
    *,
    source_map: SourceMap,
) -> list[EvidenceClaim]:
    source_lookup = {source.id: source for source in source_map.sources}
    return [
        claim
        for claim in evidence_ledger.claims
        if _is_direct_company_evidence_claim(claim, source_lookup=source_lookup)
    ]


def _enforce_direct_company_evidence(
    evidence_ledger: EvidenceLedgerModel,
    *,
    charter: ResearchCharter,
    source_map: SourceMap,
) -> EvidenceLedgerModel:
    if charter.target_type != "company" or not evidence_ledger.claims:
        return evidence_ledger
    if _direct_company_evidence_claims(evidence_ledger, source_map=source_map):
        return evidence_ledger
    if DIRECT_EVIDENCE_SUFFICIENCY_WARNING in evidence_ledger.validation_warnings:
        return evidence_ledger
    return evidence_ledger.model_copy(
        update={
            "validation_warnings": [
                *evidence_ledger.validation_warnings,
                DIRECT_EVIDENCE_SUFFICIENCY_WARNING,
            ]
        }
    )

source_scores_by_id = _source_scores_by_id
deduplicate_claims = _deduplicate_claims
validate_evidence = _validate_evidence
merge_specialist_claims = _merge_specialist_claims
enforce_direct_company_evidence = _enforce_direct_company_evidence

__all__ = [
    "DIRECT_EVIDENCE_SUFFICIENCY_WARNING",
    "deduplicate_claims",
    "enforce_direct_company_evidence",
    "merge_specialist_claims",
    "source_scores_by_id",
    "validate_evidence",
]
