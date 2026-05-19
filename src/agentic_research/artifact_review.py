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
    files_present: list[str]
    files_missing: list[str]
    evidence_claim_count: int
    unique_claim_id_count: int
    near_duplicate_count: int
    qa_high_count: int
    qa_medium_count: int
    qa_low_count: int
    final_report_published: bool
    next_recommended_action: str

    def to_markdown(self) -> str:
        present = _format_bullets(self.files_present)
        missing = _format_bullets(self.files_missing)
        final_published = "yes" if self.final_report_published else "no"
        return (
            f"# Artifact Review: {self.run_id}\n\n"
            f"- Status: {self.status}\n"
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
            "## QA Issues\n"
            f"- High: {self.qa_high_count}\n"
            f"- Medium: {self.qa_medium_count}\n"
            f"- Low: {self.qa_low_count}\n\n"
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
    final_report_published = (resolved_run_dir / "report.md").exists()
    status = str(metadata.get("status", "unknown"))
    return ArtifactReview(
        run_dir=resolved_run_dir,
        run_id=str(metadata.get("run_id") or resolved_run_dir.name),
        status=status,
        files_present=files_present,
        files_missing=files_missing,
        evidence_claim_count=len(claims),
        unique_claim_id_count=len({claim.id for claim in claims}),
        near_duplicate_count=len(find_near_duplicate_claims(claims)),
        qa_high_count=high_count,
        qa_medium_count=medium_count,
        qa_low_count=low_count,
        final_report_published=final_report_published,
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
