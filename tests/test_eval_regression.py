from __future__ import annotations

from pathlib import Path

import evals.run_regression as regression


def test_regression_harness_verifies_artifact_publication_contracts(tmp_path: Path) -> None:
    results, scorecard = regression.run(tmp_path)
    result_data = regression.results_to_dict(results)
    by_id = {result.scenario_id: result for result in results}

    assert result_data["scenario_count"] == len(results)
    assert result_data["all_passed"] is True
    assert all(result.passed for result in results)
    assert "# Regression Harness Scorecard" in scorecard

    ready = by_id["full_qa_report_ready"]
    assert ready.metadata_status == "report_ready"
    assert _check_passed(ready, "report_md_present")
    assert _check_passed(ready, "evidence_review_absent")
    assert _check_passed(ready, "report_revision_absent")

    fallback = by_id["fallback_only_evidence_blocked"]
    assert fallback.metadata_status == "evidence_needs_review"
    assert _check_passed(fallback, "evidence_review_present")
    assert _check_passed(fallback, "report_md_absent")
    assert _check_passed(fallback, "fallback_source_logged")
    assert _check_passed(fallback, "fallback_claim_not_published")

    indirect = by_id["indirect_only_company_evidence_blocked"]
    assert indirect.metadata_status == "evidence_needs_review"
    assert _check_passed(indirect, "evidence_review_present")
    assert _check_passed(indirect, "report_md_absent")

    traceability = by_id["traceability_failure_revision"]
    assert traceability.metadata_status == "draft_needs_revision"
    assert _check_passed(traceability, "report_revision_present")
    assert _check_passed(traceability, "qa_review_absent")
    assert _check_passed(traceability, "report_md_absent")

    continued = by_id["continue_report_ready"]
    assert continued.metadata_status == "report_ready"
    assert _check_passed(continued, "report_md_present")
    assert _check_passed(continued, "qa_review_present")


def _check_passed(result: regression.RegressionResult, name: str) -> bool:
    return any(check.name == name and check.passed for check in result.checks)
