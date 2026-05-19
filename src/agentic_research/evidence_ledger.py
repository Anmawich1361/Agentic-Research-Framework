from __future__ import annotations

from collections.abc import Iterable, Mapping
from urllib.parse import urlsplit, urlunsplit

from agentic_research.models import (
    EvidenceClaim,
    EvidenceLedger as EvidenceLedgerModel,
    SourceCandidate,
    SourceMap,
    SourceScore,
)


def _normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    stripped = url.strip()
    parsed = urlsplit(stripped)
    if parsed.scheme and parsed.netloc:
        path = parsed.path.rstrip("/")
        return urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                path,
                parsed.query,
                "",
            )
        )
    return stripped.rstrip("/").lower()


def _source_scores_from_map(source_map: SourceMap | None) -> dict[str, SourceScore]:
    if source_map is None:
        return {}
    return {score.source_id: score for score in source_map.scores}


def _sources_by_url(source_map: SourceMap | None) -> dict[str, SourceCandidate]:
    if source_map is None:
        return {}
    sources: dict[str, SourceCandidate] = {}
    for source in source_map.sources:
        normalized = _normalize_url(source.url)
        if normalized is not None:
            sources[normalized] = source
    return sources


def _normalized_text(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def evidence_claim_content_key(claim: EvidenceClaim) -> tuple[str, ...]:
    return (
        _normalized_text(claim.claim),
        claim.claim_type,
        claim.confidence,
        _normalized_text(claim.report_section),
        claim.source_id or "",
        claim.source_title or "",
        _normalize_url(claim.source_url) or "",
        claim.source_type or "",
        _normalized_text(claim.quote_or_excerpt),
    )


class EvidenceLedger:
    def __init__(self, claims: Iterable[EvidenceClaim] | None = None) -> None:
        self.claims = list(claims or [])
        self.validation_warnings: list[str] = []

    def add_claim(self, claim: EvidenceClaim) -> None:
        self.claims.append(claim)

    def list_claims_by_section(self, section: str) -> list[EvidenceClaim]:
        return [claim for claim in self.claims if claim.report_section == section]

    def validate(
        self,
        source_scores: Mapping[str, SourceScore] | None = None,
        source_map: SourceMap | None = None,
        high_confidence_authority_floor: float = 4,
    ) -> list[str]:
        warnings: list[str] = []
        scores: dict[str, SourceScore] = _source_scores_from_map(source_map)
        if source_scores is not None:
            scores.update(source_scores)
        sources_by_id = (
            {source.id: source for source in source_map.sources}
            if source_map is not None
            else {}
        )
        sources_by_normalized_url = _sources_by_url(source_map)
        duplicate_positions: dict[str, list[int]] = {}
        duplicate_content_keys: dict[str, set[tuple[str, ...]]] = {}
        for index, claim in enumerate(self.claims, start=1):
            duplicate_positions.setdefault(claim.id, []).append(index)
            duplicate_content_keys.setdefault(claim.id, set()).add(
                evidence_claim_content_key(claim)
            )

        for claim_id, positions in duplicate_positions.items():
            if len(positions) <= 1:
                continue
            position_text = ", ".join(str(position) for position in positions)
            content_description = (
                "identical claim/source content"
                if len(duplicate_content_keys[claim_id]) == 1
                else "conflicting claim/source content"
            )
            warnings.append(
                f"{claim_id}: duplicate evidence claim id appears {len(positions)} "
                f"times at positions {position_text} with {content_description}."
            )

        for claim in self.claims:
            if claim.claim_type == "fact" and not (claim.source_id or claim.source_url):
                warnings.append(f"{claim.id}: fact claim must include a source id or URL.")

            known_source: SourceCandidate | None = None
            score: SourceScore | None = None
            if claim.source_id:
                known_source = sources_by_id.get(claim.source_id)
                if source_map is not None and known_source is None:
                    warnings.append(
                        f"{claim.id}: unknown source id {claim.source_id} is not in the source map."
                    )
                score = scores.get(claim.source_id)

            normalized_claim_url = _normalize_url(claim.source_url)
            if normalized_claim_url and known_source is None:
                known_source = sources_by_normalized_url.get(normalized_claim_url)
                if known_source is not None and score is None:
                    score = scores.get(known_source.id)

            if claim.source_id and claim.source_url and known_source is not None:
                normalized_source_url = _normalize_url(known_source.url)
                if normalized_claim_url != normalized_source_url:
                    warnings.append(
                        f"{claim.id}: source_url {claim.source_url} does not match source map "
                        f"URL for {claim.source_id} ({known_source.url})."
                    )

            if claim.claim_type == "fact" and claim.confidence == "high":
                if source_map is not None and known_source is None:
                    warnings.append(
                        f"{claim.id}: high-confidence fact claim must use a known source."
                    )
                elif known_source is not None and score is None:
                    warnings.append(
                        f"{claim.id}: high-confidence fact claim uses known source "
                        f"{known_source.id} without an authority score."
                    )

            if claim.confidence == "high" and score is not None and (
                score.authority_score < high_confidence_authority_floor
            ):
                warnings.append(
                    f"{claim.id}: high-confidence claim uses low-authority source "
                    f"{score.source_id} (authority {score.authority_score})."
                )

        self.validation_warnings = warnings
        return warnings

    def to_model(self) -> EvidenceLedgerModel:
        return EvidenceLedgerModel(
            claims=self.claims,
            validation_warnings=self.validation_warnings,
        )


def raise_if_report_has_unsupported_claims(ledger: EvidenceLedger) -> None:
    if not ledger.validation_warnings:
        ledger.validate()
    if ledger.validation_warnings:
        warning_text = "; ".join(ledger.validation_warnings)
        raise ValueError(f"Cannot generate report with unsupported evidence claims: {warning_text}")


__all__ = [
    "EvidenceLedger",
    "evidence_claim_content_key",
    "raise_if_report_has_unsupported_claims",
]
