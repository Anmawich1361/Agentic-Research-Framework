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
    _write_json(
        run_dir / "source_fetch_log.json",
        {
            "results": [
                {
                    "source_id": "src_costco",
                    "url": "https://example.com/costco",
                    "status": "fetched",
                    "text_char_count": 100,
                    "chunk_count": 1,
                },
                {
                    "source_id": "src_blocked",
                    "url": "https://example.com/blocked",
                    "status": "failed",
                    "failure_reason": "http_403",
                    "error": "HTTP 403",
                    "text_char_count": 0,
                    "chunk_count": 0,
                },
            ]
        },
    )
    _write_json(
        run_dir / "source_discovery_review.json",
        {
            "query_count": 7,
            "raw_result_count": 4,
            "selected_source_count": 2,
            "repair_added_source_ids": ["repair_earnings_release_1"],
            "unresolved_gaps": ["Missing source type: market_data"],
            "coverage_gaps": [
                "Investment brief missing fetched market/valuation source."
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
    assert review.source_fetch_fetched_count == 1
    assert review.source_fetch_failed_count == 1
    assert review.source_discovery_query_count == 7
    assert review.source_discovery_raw_result_count == 4
    assert review.source_discovery_repair_added_count == 1
    assert review.source_discovery_unresolved_gap_count == 1
    assert review.source_discovery_coverage_gap_count == 1
    assert review.publication_state == "qa_blocked"
    assert any("QA blocked publication" in warning for warning in review.blocking_warnings)
    assert any("1 failed source fetch" in warning for warning in review.blocking_warnings)
    assert any(
        "Source discovery has 1 unresolved source gap" in warning
        for warning in review.blocking_warnings
    )
    assert any(
        "Source coverage has 1 blocking coverage gap" in warning
        for warning in review.blocking_warnings
    )
    assert review.final_report_published is False
    assert "Final report published: no" in markdown
    assert "Publication state: qa_blocked" in markdown
    assert "Source fetches: 1 fetched, 0 fallback, 1 failed, 0 skipped" in markdown
    assert "Source discovery queries: 7" in markdown
    assert "Repair-added sources: 1" in markdown
    assert "Coverage gaps: 1" in markdown
    assert "Fix high-severity QA blockers before publishing the final report." in markdown


def test_write_artifact_review_saves_markdown(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_empty"
    run_dir.mkdir()

    path = write_artifact_review(run_dir)

    assert path == run_dir / "artifact_review.md"
    assert "# Artifact Review: run_empty" in path.read_text(encoding="utf-8")
