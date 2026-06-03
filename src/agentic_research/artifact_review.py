from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agentic_research.evidence_quality import find_near_duplicate_claims
from agentic_research.models import EvidenceClaim, StrictModel


EXPECTED_ARTIFACTS = (
    "metadata.json",
    "charter.json",
    "research_plan.json",
    "sources.json",
    "source_map.json",
    "source_discovery_review.json",
    "source_content.json",
    "source_fetch_log.json",
    "checkpoint.md",
    "evidence_ledger.json",
    "specialist_analyses.json",
    "draft_report.md",
    "qa_review.json",
    "report.md",
    "evidence_review.md",
)


class ArtifactReview(StrictModel):
    run_dir: Path
    run_id: str
    status: str
    publication_state: str
    files_present: list[str]
    files_missing: list[str]
    evidence_claim_count: int
    unique_claim_id_count: int
    near_duplicate_count: int
    source_fetch_fetched_count: int
    source_fetch_fallback_count: int
    source_fetch_failed_count: int
    source_fetch_skipped_count: int
    source_discovery_query_count: int
    source_discovery_raw_result_count: int
    source_discovery_repair_added_count: int
    source_discovery_unresolved_gap_count: int
    source_discovery_coverage_gap_count: int
    qa_high_count: int
    qa_medium_count: int
    qa_low_count: int
    final_report_published: bool
    blocking_warnings: list[str]
    next_recommended_action: str

    def to_markdown(self) -> str:
        present = _format_bullets(self.files_present)
        missing = _format_bullets(self.files_missing)
        warnings = _format_bullets(self.blocking_warnings)
        final_published = "yes" if self.final_report_published else "no"
        return (
            f"# Artifact Review: {self.run_id}\n\n"
            f"- Status: {self.status}\n"
            f"- Publication state: {self.publication_state}\n"
            f"- Final report published: {final_published}\n\n"
            "## Files\n"
            "Present:\n"
            f"{present}\n\n"
            "Missing:\n"
            f"{missing}\n\n"
            "## Evidence\n"
            f"- Evidence claim count: {self.evidence_claim_count}\n"
            f"- Unique claim ID count: {self.unique_claim_id_count}\n"
            f"- Near-duplicate count: {self.near_duplicate_count}\n\n"
            "## Source Fetches\n"
            "- Source fetches: "
            f"{self.source_fetch_fetched_count} fetched, "
            f"{self.source_fetch_fallback_count} fallback, "
            f"{self.source_fetch_failed_count} failed, "
            f"{self.source_fetch_skipped_count} skipped\n\n"
            "## Source Discovery\n"
            f"- Source discovery queries: {self.source_discovery_query_count}\n"
            f"- Raw search results: {self.source_discovery_raw_result_count}\n"
            f"- Repair-added sources: {self.source_discovery_repair_added_count}\n"
            f"- Unresolved source gaps: {self.source_discovery_unresolved_gap_count}\n"
            f"- Coverage gaps: {self.source_discovery_coverage_gap_count}\n\n"
            "## QA Issues\n"
            f"- High: {self.qa_high_count}\n"
            f"- Medium: {self.qa_medium_count}\n"
            f"- Low: {self.qa_low_count}\n\n"
            "## Blocking Warnings\n"
            f"{warnings}\n\n"
            "## Next Recommended Action\n"
            f"{self.next_recommended_action}\n"
        )


def _format_bullets(items: list[str]) -> str:
    if not items:
        return "- None"
    return "\n".join(f"- {item}" for item in items)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_evidence_claims(run_dir: Path) -> list[EvidenceClaim]:
    ledger = _load_json(run_dir / "evidence_ledger.json")
    claims: list[EvidenceClaim] = []
    for claim_payload in ledger.get("claims", []):
        claims.append(EvidenceClaim.model_validate(claim_payload))
    return claims


def _qa_counts(run_dir: Path) -> tuple[int, int, int]:
    review = _load_json(run_dir / "qa_review.json")
    high = medium = low = 0
    for issue in review.get("issues", []):
        severity = issue.get("severity")
        if severity == "high":
            high += 1
        elif severity == "medium":
            medium += 1
        elif severity == "low":
            low += 1
    return high, medium, low


def _source_fetch_counts(run_dir: Path) -> tuple[int, int, int, int]:
    fetch_log = _load_json(run_dir / "source_fetch_log.json")
    fetched = fallback = failed = skipped = 0
    for result in fetch_log.get("results", []):
        status = result.get("status")
        if status == "fetched":
            fetched += 1
        elif status == "fallback":
            fallback += 1
        elif status == "failed":
            failed += 1
        elif status == "skipped":
            skipped += 1
    return fetched, fallback, failed, skipped


def _source_discovery_counts(run_dir: Path) -> tuple[int, int, int, int, int]:
    review = _load_json(run_dir / "source_discovery_review.json")
    return (
        int(review.get("query_count") or 0),
        int(review.get("raw_result_count") or 0),
        len(review.get("repair_added_source_ids", [])),
        len(review.get("unresolved_gaps", [])),
        len(review.get("coverage_gaps", [])),
    )


def _plural(count: int, noun: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count} {noun}{suffix}"


def _publication_state(
    *,
    status: str,
    final_report_published: bool,
    high_count: int,
) -> str:
    if final_report_published and status == "report_ready":
        return "final_published"
    if status == "needs_review" or high_count > 0:
        return "qa_blocked"
    if status == "draft_needs_revision":
        return "pre_qa_revision_needed"
    if status == "evidence_needs_review":
        return "evidence_blocked"
    if status == "draft_needs_qa":
        return "draft_pending_qa"
    if status == "checkpoint_ready":
        return "checkpoint_waiting"
    if status == "failed":
        return "failed"
    return "not_published"


def _blocking_warnings(
    *,
    run_dir: Path,
    status: str,
    high_count: int,
    source_fetch_fallback_count: int,
    source_fetch_failed_count: int,
    source_fetch_skipped_count: int,
    source_discovery_unresolved_gap_count: int,
    source_discovery_coverage_gap_count: int,
    final_report_published: bool,
) -> list[str]:
    warnings: list[str] = []
    if source_fetch_failed_count:
        warnings.append(f"{_plural(source_fetch_failed_count, 'failed source fetch')}.")
    if source_fetch_skipped_count:
        warnings.append(f"{_plural(source_fetch_skipped_count, 'skipped source fetch')}.")
    if source_fetch_fallback_count:
        warnings.append(
            f"{_plural(source_fetch_fallback_count, 'fallback-only source fetch')}."
        )
    if source_discovery_unresolved_gap_count:
        warnings.append(
            f"Source discovery has "
            f"{_plural(source_discovery_unresolved_gap_count, 'unresolved source gap')}."
        )
    if source_discovery_coverage_gap_count:
        warnings.append(
            f"Source coverage has "
            f"{_plural(source_discovery_coverage_gap_count, 'blocking coverage gap')}."
        )

    ledger = _load_json(run_dir / "evidence_ledger.json")
    for warning in ledger.get("validation_warnings", []):
        warnings.append(f"Evidence validation: {warning}")

    if status == "evidence_needs_review":
        warnings.append("Evidence validation blocked synthesis. Inspect evidence_review.md.")
    if status == "draft_needs_revision" or (run_dir / "report_revision.md").exists():
        warnings.append("Pre-QA report validation blocked QA. Inspect report_revision.md.")
    if status == "needs_review" or high_count > 0:
        warnings.append(
            f"QA blocked publication with {_plural(high_count, 'high-severity issue')}."
        )
    if status == "failed":
        warnings.append("Run failed. Inspect failure_report.md and error.json.")
    if final_report_published:
        warnings.append("Final report published after QA passed.")
    return warnings


def _next_action(
    *,
    status: str,
    high_count: int,
    evidence_claim_count: int,
    final_report_published: bool,
) -> str:
    if status == "evidence_needs_review":
        return "Fix evidence validation and evidence-quality warnings before synthesis."
    if high_count > 0 or status == "needs_review":
        return "Fix high-severity QA blockers before publishing the final report."
    if status == "draft_needs_revision":
        return "Revise the draft structure and rerun the full QA workflow."
    if status == "draft_needs_qa":
        return "Run the full workflow with QA before publishing."
    if status == "checkpoint_ready":
        return "Review the checkpoint, then run the approved full workflow."
    if final_report_published:
        return "Inspect the final report quality before relying on it."
    if evidence_claim_count == 0:
        return "Inspect missing evidence artifacts before continuing."
    return "Inspect artifact gaps and rerun the narrowest failing workflow step."


def build_artifact_review(run_dir: str | Path) -> ArtifactReview:
    resolved_run_dir = Path(run_dir)
    metadata = _load_json(resolved_run_dir / "metadata.json")
    files_present = sorted(
        name for name in EXPECTED_ARTIFACTS if (resolved_run_dir / name).exists()
    )
    files_missing = sorted(
        name for name in EXPECTED_ARTIFACTS if not (resolved_run_dir / name).exists()
    )
    claims = _load_evidence_claims(resolved_run_dir)
    high_count, medium_count, low_count = _qa_counts(resolved_run_dir)
    (
        source_fetch_fetched_count,
        source_fetch_fallback_count,
        source_fetch_failed_count,
        source_fetch_skipped_count,
    ) = _source_fetch_counts(resolved_run_dir)
    (
        source_discovery_query_count,
        source_discovery_raw_result_count,
        source_discovery_repair_added_count,
        source_discovery_unresolved_gap_count,
        source_discovery_coverage_gap_count,
    ) = _source_discovery_counts(resolved_run_dir)
    final_report_published = (resolved_run_dir / "report.md").exists()
    status = str(metadata.get("status", "unknown"))
    publication_state = _publication_state(
        status=status,
        final_report_published=final_report_published,
        high_count=high_count,
    )
    return ArtifactReview(
        run_dir=resolved_run_dir,
        run_id=str(metadata.get("run_id") or resolved_run_dir.name),
        status=status,
        publication_state=publication_state,
        files_present=files_present,
        files_missing=files_missing,
        evidence_claim_count=len(claims),
        unique_claim_id_count=len({claim.id for claim in claims}),
        near_duplicate_count=len(find_near_duplicate_claims(claims)),
        source_fetch_fetched_count=source_fetch_fetched_count,
        source_fetch_fallback_count=source_fetch_fallback_count,
        source_fetch_failed_count=source_fetch_failed_count,
        source_fetch_skipped_count=source_fetch_skipped_count,
        source_discovery_query_count=source_discovery_query_count,
        source_discovery_raw_result_count=source_discovery_raw_result_count,
        source_discovery_repair_added_count=source_discovery_repair_added_count,
        source_discovery_unresolved_gap_count=source_discovery_unresolved_gap_count,
        source_discovery_coverage_gap_count=source_discovery_coverage_gap_count,
        qa_high_count=high_count,
        qa_medium_count=medium_count,
        qa_low_count=low_count,
        final_report_published=final_report_published,
        blocking_warnings=_blocking_warnings(
            run_dir=resolved_run_dir,
            status=status,
            high_count=high_count,
            source_fetch_fallback_count=source_fetch_fallback_count,
            source_fetch_failed_count=source_fetch_failed_count,
            source_fetch_skipped_count=source_fetch_skipped_count,
            source_discovery_unresolved_gap_count=source_discovery_unresolved_gap_count,
            source_discovery_coverage_gap_count=source_discovery_coverage_gap_count,
            final_report_published=final_report_published,
        ),
        next_recommended_action=_next_action(
            status=status,
            high_count=high_count,
            evidence_claim_count=len(claims),
            final_report_published=final_report_published,
        ),
    )


def write_artifact_review(run_dir: str | Path) -> Path:
    resolved_run_dir = Path(run_dir)
    review = build_artifact_review(resolved_run_dir)
    path = resolved_run_dir / "artifact_review.md"
    path.write_text(review.to_markdown(), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Review artifacts for an ARF run directory.")
    parser.add_argument("run_dir", help="Path to a runs/<run_id> directory.")
    args = parser.parse_args()
    path = write_artifact_review(args.run_dir)
    print(path)


if __name__ == "__main__":
    main()


__all__ = [
    "ArtifactReview",
    "build_artifact_review",
    "write_artifact_review",
]
