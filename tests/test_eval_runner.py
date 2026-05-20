import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import httpx

import evals.run_eval as eval_runner


def test_eval_runner_loads_three_fixtures_and_prints_scorecard() -> None:
    result = subprocess.run(
        [sys.executable, "evals/run_eval.py"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0
    assert "# Evaluation Scorecard" in result.stdout
    assert "company_meeting_prep" in result.stdout
    assert "Company meeting prep brief" in result.stdout
    assert "investment_memo" in result.stdout
    assert "industry_primer" in result.stdout
    assert "fixtures passed" in result.stdout
    assert "source_grounding" in result.stdout
    assert "evidence_depth" in result.stdout
    assert "unsupported_claims" in result.stdout
    assert "report_usefulness" in result.stdout
    assert "recency_handling" in result.stdout
    assert "source_diversity" in result.stdout


def test_eval_fixtures_include_required_phase_12_fields() -> None:
    fixtures = sorted(Path("evals/fixtures").glob("*.json"))

    assert len(fixtures) >= 3
    for fixture_path in fixtures:
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        assert fixture["request"]
        assert fixture["source_map"]["sources"]
        assert fixture["evidence_ledger"]["claims"]
        assert fixture["expected_qa"]
        assert fixture["expected_report_sections"]


def test_eval_runner_loads_all_fixture_ids() -> None:
    fixtures = eval_runner.load_fixtures(Path("evals/fixtures"))

    assert {fixture["id"] for fixture in fixtures} == {
        "company_meeting_prep",
        "industry_primer",
        "investment_memo",
    }


def test_eval_runner_produces_machine_readable_result_structure() -> None:
    fixtures = eval_runner.load_fixtures(Path("evals/fixtures"))
    results, _scorecard = eval_runner.run(Path("evals/fixtures"))
    result_data = eval_runner.results_to_dict(results)

    assert result_data["fixture_count"] == len(fixtures)
    assert result_data["passed_count"] == len(fixtures)
    assert result_data["failed_count"] == 0
    assert result_data["all_passed"] is True
    assert result_data["fixtures"]

    first = result_data["fixtures"][0]
    assert {
        "fixture_id",
        "name",
        "score",
        "passed",
        "checks",
        "qa_issue_counts",
        "qa_issue_categories",
    } <= first.keys()
    assert {
        "source_grounding",
        "evidence_depth",
        "unsupported_claims",
        "report_usefulness",
        "recency_handling",
        "source_diversity",
    } <= {check["name"] for check in first["checks"]}


def test_eval_runner_flags_unsupported_claims_in_fixture() -> None:
    fixture = deepcopy(eval_runner.load_fixtures(Path("evals/fixtures"))[0])
    fixture["id"] = "fixture_with_unsupported_claim"
    fixture["draft_report"]["markdown"] = fixture["draft_report"]["markdown"].replace(
        "## Executive Summary\n",
        "## Executive Summary\nCostco has a durable supplier advantage in grocery.\n",
    )

    result = eval_runner.evaluate_fixture(fixture)
    result_data = result.to_dict()

    assert result.passed is False
    assert any(
        check.name == "unsupported_claims" and not check.passed
        for check in result.checks
    )
    assert any(
        issue["category"] == "unsupported_claim"
        and "durable supplier advantage" in issue["problem"]
        for issue in result_data["qa_issues"]
    )


def test_eval_runner_does_not_call_live_apis_by_default(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def fail_network(*args, **kwargs):
        raise AssertionError("eval runner should not make network calls")

    monkeypatch.setattr(httpx, "get", fail_network)
    monkeypatch.setattr(httpx, "post", fail_network)

    results, _scorecard = eval_runner.run(Path("evals/fixtures"))

    assert all(result.passed for result in results)
