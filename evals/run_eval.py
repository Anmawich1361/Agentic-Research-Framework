#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentic_research.models import EvidenceLedger, QAReview, Report, SourceMap  # noqa: E402
from agentic_research.qa import run_deterministic_qa_checks  # noqa: E402
from agentic_research.report_validation import has_heading  # noqa: E402


RUBRIC_NAMES = [
    "source_grounding",
    "evidence_depth",
    "report_usefulness",
    "unsupported_claims",
    "source_diversity",
    "recency_handling",
]


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class FixtureResult:
    fixture_id: str
    name: str
    score: int
    passed: bool
    checks: list[CheckResult]
    qa_review: QAReview


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _issue_count(review: QAReview, severity: str) -> int:
    return sum(1 for issue in review.issues if issue.severity == severity)


def _issue_categories(review: QAReview) -> set[str]:
    return {issue.category for issue in review.issues if issue.category is not None}


def _claim_source_ids(ledger: EvidenceLedger) -> set[str]:
    return {
        claim.source_id
        for claim in ledger.claims
        if claim.source_id is not None and claim.source_id.strip()
    }


def _recent_source_count(source_map: SourceMap) -> int:
    return sum(1 for source in source_map.sources if source.publication_date)


def _check_expected_sections(report: Report, expected_sections: list[str]) -> CheckResult:
    missing = [section for section in expected_sections if not has_heading(report.markdown, section)]
    return CheckResult(
        name="report_usefulness",
        passed=not missing,
        detail="all expected sections present"
        if not missing
        else f"missing sections: {', '.join(missing)}",
    )


def _check_issue_limit(
    *,
    review: QAReview,
    severity: str,
    limit: int | None,
) -> CheckResult:
    count = _issue_count(review, severity)
    if limit is None:
        return CheckResult(
            name=f"qa_{severity}",
            passed=True,
            detail=f"{count} {severity} issues; no limit configured",
        )
    return CheckResult(
        name=f"qa_{severity}",
        passed=count <= limit,
        detail=f"{count} {severity} issues; limit {limit}",
    )


def _check_category_expectations(
    *,
    review: QAReview,
    required_categories: list[str],
    forbidden_categories: list[str],
) -> list[CheckResult]:
    categories = _issue_categories(review)
    missing_required = sorted(set(required_categories) - categories)
    present_forbidden = sorted(set(forbidden_categories) & categories)
    return [
        CheckResult(
            name="required_qa_categories",
            passed=not missing_required,
            detail="all required issue categories present"
            if not missing_required
            else f"missing categories: {', '.join(missing_required)}",
        ),
        CheckResult(
            name="forbidden_qa_categories",
            passed=not present_forbidden,
            detail="no forbidden issue categories present"
            if not present_forbidden
            else f"forbidden categories present: {', '.join(present_forbidden)}",
        ),
    ]


def evaluate_fixture(fixture: dict[str, Any]) -> FixtureResult:
    fixture_id = fixture["id"]
    name = fixture.get("name", fixture_id)
    source_map = SourceMap.model_validate(fixture["source_map"])
    evidence_ledger = EvidenceLedger.model_validate(fixture["evidence_ledger"])
    report = Report.model_validate(fixture["draft_report"])
    expected_qa = fixture.get("expected_qa", {})

    review = run_deterministic_qa_checks(
        source_map=source_map,
        evidence_ledger=evidence_ledger,
        draft_report=report,
        template_name=fixture.get("template_name"),
    )

    checks: list[CheckResult] = [
        _check_expected_sections(report, fixture.get("expected_report_sections", [])),
        _check_issue_limit(
            review=review,
            severity="high",
            limit=expected_qa.get("max_high_issues"),
        ),
        _check_issue_limit(
            review=review,
            severity="medium",
            limit=expected_qa.get("max_medium_issues"),
        ),
        _check_issue_limit(
            review=review,
            severity="low",
            limit=expected_qa.get("max_low_issues"),
        ),
    ]
    checks.extend(
        _check_category_expectations(
            review=review,
            required_categories=expected_qa.get("required_categories", []),
            forbidden_categories=expected_qa.get("forbidden_categories", []),
        )
    )

    expected_ready = expected_qa.get("ready_to_publish")
    if expected_ready is not None:
        checks.append(
            CheckResult(
                name="ready_to_publish",
                passed=review.ready_to_publish is expected_ready,
                detail=f"actual={review.ready_to_publish}, expected={expected_ready}",
            )
        )

    min_claims = int(expected_qa.get("min_claim_count", 0))
    checks.append(
        CheckResult(
            name="evidence_depth",
            passed=len(evidence_ledger.claims) >= min_claims,
            detail=f"{len(evidence_ledger.claims)} claims; minimum {min_claims}",
        )
    )

    min_sources = int(expected_qa.get("min_source_count", 0))
    source_count = len(_claim_source_ids(evidence_ledger))
    checks.append(
        CheckResult(
            name="source_diversity",
            passed=source_count >= min_sources,
            detail=f"{source_count} cited source IDs; minimum {min_sources}",
        )
    )

    if expected_qa.get("requires_recent_source", False):
        recent_count = _recent_source_count(source_map)
        checks.append(
            CheckResult(
                name="recency_handling",
                passed=recent_count > 0
                and "missing_recent_signal" not in _issue_categories(review)
                and "stale_or_unclear_recency" not in _issue_categories(review),
                detail=f"{recent_count} sources include publication_date",
            )
        )

    high_unsupported = sum(
        1
        for issue in review.issues
        if issue.severity == "high" and issue.category == "unsupported_claim"
    )
    checks.append(
        CheckResult(
            name="unsupported_claims",
            passed=high_unsupported <= int(expected_qa.get("max_high_unsupported_claims", 0)),
            detail=f"{high_unsupported} high unsupported-claim issues",
        )
    )

    checks.append(
        CheckResult(
            name="source_grounding",
            passed=not any(
                issue.severity == "high"
                and issue.category in {"unsupported_claim", "source_gap"}
                for issue in review.issues
            ),
            detail="no high-severity grounding issues"
            if not any(issue.severity == "high" for issue in review.issues)
            else "high-severity issues present",
        )
    )

    passed_count = sum(1 for check in checks if check.passed)
    score = round((passed_count / len(checks)) * 100)
    return FixtureResult(
        fixture_id=fixture_id,
        name=name,
        score=score,
        passed=all(check.passed for check in checks),
        checks=checks,
        qa_review=review,
    )


def load_fixtures(fixtures_dir: Path) -> list[dict[str, Any]]:
    paths = sorted(fixtures_dir.glob("*.json"))
    if not paths:
        raise FileNotFoundError(f"No fixture JSON files found in {fixtures_dir}")
    return [_load_json(path) for path in paths]


def render_scorecard(results: list[FixtureResult]) -> str:
    passed_count = sum(1 for result in results if result.passed)
    lines = [
        "# Evaluation Scorecard",
        "",
        f"- Fixtures: {len(results)}",
        f"- Result: {passed_count}/{len(results)} fixtures passed",
        f"- Rubrics: {', '.join(RUBRIC_NAMES)}",
        "",
        "| Fixture | Status | Score | High | Medium | Low |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        lines.append(
            "| "
            f"{result.fixture_id} | {status} | {result.score} | "
            f"{_issue_count(result.qa_review, 'high')} | "
            f"{_issue_count(result.qa_review, 'medium')} | "
            f"{_issue_count(result.qa_review, 'low')} |"
        )

    failed = [result for result in results if not result.passed]
    if failed:
        lines.extend(["", "## Failures"])
        for result in failed:
            lines.append("")
            lines.append(f"### {result.fixture_id}")
            for check in result.checks:
                if not check.passed:
                    lines.append(f"- {check.name}: {check.detail}")

    return "\n".join(lines) + "\n"


def run(fixtures_dir: Path) -> tuple[list[FixtureResult], str]:
    fixtures = load_fixtures(fixtures_dir)
    results = [evaluate_fixture(fixture) for fixture in fixtures]
    return results, render_scorecard(results)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic research quality evals.")
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=ROOT / "evals" / "fixtures",
        help="Directory containing fixture JSON files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write the markdown scorecard.",
    )
    args = parser.parse_args(argv)

    results, scorecard = run(args.fixtures_dir)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(scorecard, encoding="utf-8")
    print(scorecard, end="")
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
