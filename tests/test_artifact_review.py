import json
from pathlib import Path

from agentic_research.artifact_review import build_artifact_review, write_artifact_review


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_build_artifact_review_summarizes_run_quality(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_20260518T000000Z_demo"
    run_dir.mkdir()
    _write_json(
        run_dir / "metadata.json",
        {
            "run_id": "run_20260518T000000Z_demo",
            "created_at": "2026-05-18T00:00:00+00:00",
            "request": "Research Costco before a supplier meeting",
            "status": "needs_review",
            "mode": "brief",
            "lens": "sales",
            "mock": False,
        },
    )
    _write_json(
        run_dir / "evidence_ledger.json",
        {
            "claims": [
                {
                    "id": "c1",
                    "claim": "Costco says suppliers must comply with its vendor code of conduct.",
                    "claim_type": "fact",
                    "confidence": "medium",
                    "report_section": "overview",
                    "source_id": "src_costco",
                },
                {
                    "id": "r1",
                    "claim": "Costco states that suppliers must comply with Costco's vendor code of conduct.",
                    "claim_type": "fact",
                    "confidence": "medium",
                    "report_section": "overview",
                    "source_id": "src_costco",
                },
            ],
            "validation_warnings": [],
        },
    )
    _write_json(
        run_dir / "qa_review.json",
        {
            "ready_to_publish": False,
            "issues": [
                {
                    "severity": "high",
                    "category": "unsupported_claim",
                    "problem": "Unsupported broad claim.",
                    "suggested_fix": "Cite direct evidence.",
                    "affected_section": "Key Findings",
                },
                {
                    "severity": "medium",
                    "category": "source_gap",
                    "problem": "Needs recent source.",
                    "suggested_fix": "Add a recent source.",
                    "affected_section": "Recent Developments",
                },
            ],
        },
    )
    (run_dir / "draft_report.md").write_text("# Draft", encoding="utf-8")

    review = build_artifact_review(run_dir)
    markdown = review.to_markdown()

    assert review.status == "needs_review"
    assert review.evidence_claim_count == 2
    assert review.unique_claim_id_count == 2
    assert review.near_duplicate_count == 1
    assert review.qa_high_count == 1
    assert review.final_report_published is False
    assert "Final report published: no" in markdown
    assert "Fix high-severity QA blockers before publishing the final report." in markdown


def test_write_artifact_review_saves_markdown(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_empty"
    run_dir.mkdir()

    path = write_artifact_review(run_dir)

    assert path == run_dir / "artifact_review.md"
    assert "# Artifact Review: run_empty" in path.read_text(encoding="utf-8")
