from __future__ import annotations

from collections.abc import Iterable, Mapping

from agentic_research.models import EvidenceClaim, EvidenceLedger as EvidenceLedgerModel, SourceScore


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
        high_confidence_authority_floor: float = 4,
    ) -> list[str]:
        warnings: list[str] = []
        scores = source_scores or {}

        for claim in self.claims:
            if claim.claim_type == "fact" and not (claim.source_id or claim.source_url):
                warnings.append(f"{claim.id}: fact claim must include a source id or URL.")

            score = scores.get(claim.source_id or "")
            if (
                claim.confidence == "high"
                and score is not None
                and score.authority_score < high_confidence_authority_floor
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


__all__ = ["EvidenceLedger", "raise_if_report_has_unsupported_claims"]
