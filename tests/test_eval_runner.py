import json
import subprocess
import sys
from pathlib import Path


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
    assert "investment_memo" in result.stdout
    assert "industry_primer" in result.stdout
    assert "fixtures passed" in result.stdout


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
