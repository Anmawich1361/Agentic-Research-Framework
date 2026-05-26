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

from agentic_research.evidence_pipeline import (  # noqa: E402
    DIRECT_EVIDENCE_SUFFICIENCY_WARNING,
    enforce_direct_company_evidence,
    validate_evidence,
)
from agentic_research.models import (  # noqa: E402
    EvidenceLedger,
    QAReview,
    Report,
    ResearchCharter,
    SourceFetchLog,
    SourceMap,
)
from agentic_research.qa import run_deterministic_qa_checks  # noqa: E402
from agentic_research.report_validation import has_heading  # noqa: E402
from agentic_research.run_artifacts import has_blocking_evidence_warnings  # noqa: E402


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class FixtureResult:
    fixture_id: str
    name: str
    score: int
    passed: bool
    checks: list[CheckResult]
    qa_review: QAReview
    evidence_ledger: EvidenceLedger

    def to_dict(self) -> dict[str, Any]:
        failed_checks = [check for check in self.checks if not check.passed]
        return {
            "fixture_id": self.fixture_id,
            "name": self.name,
            "score": self.score,
            "passed": self.passed,
            "checks": [check.to_dict() for check in self.checks],
            "failed_checks": [check.to_dict() for check in failed_checks],
            "failure_reasons": [
                f"{check.name}: {check.detail}" for check in failed_checks
            ],
            "evidence_claim_ids": [claim.id for claim in self.evidence_ledger.claims],
            "evidence_validation_warnings": list(
                self.evidence_ledger.validation_warnings
            ),
            "qa_issue_counts": {
                "high": _issue_count(self.qa_review, "high"),
                "medium": _issue_count(self.qa_review, "medium"),
                "low": _issue_count(self.qa_review, "low"),
            },
            "qa_issue_categories": sorted(_issue_categories(self.qa_review)),
            "qa_issues": [
                issue.model_dump(mode="json")
                for issue in self.qa_review.issues
            ],
        }


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _issue_count(review: QAReview, severity: str) -> int:
    return sum(1 for issue in review.issues if issue.severity == severity)


def _issue_categories(review: QAReview) -> set[str]:
    return {issue.category for issue in review.issues if issue.category is not None}


def _issue_categories_for_severity(review: QAReview, severity: str) -> set[str]:
    return {
        issue.category
        for issue in review.issues
        if issue.severity == severity and issue.category is not None
    }


def _issue_details(
    review: QAReview,
    *,
    severity: str | None = None,
    categories: set[str] | None = None,
) -> list[str]:
    details: list[str] = []
    for issue in review.issues:
        if severity is not None and issue.severity != severity:
            continue
        if categories is not None and issue.category not in categories:
            continue
        category = issue.category or "uncategorized"
        details.append(f"{issue.severity}/{category}: {issue.problem}")
    return details


def _detail_or_default(details: list[str], default: str) -> str:
    return default if not details else "; ".join(details)


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


def _check_issue_floor(
    *,
    review: QAReview,
    severity: str,
    minimum: int | None,
) -> CheckResult:
    count = _issue_count(review, severity)
    if minimum is None:
        return CheckResult(
            name=f"qa_{severity}_min",
            passed=True,
            detail=f"{count} {severity} issues; no minimum configured",
        )
    return CheckResult(
        name=f"qa_{severity}_min",
        passed=count >= minimum,
        detail=f"{count} {severity} issues; minimum {minimum}",
    )


def _check_required_severity_categories(
    *,
    review: QAReview,
    severity: str,
    required_categories: list[str],
) -> CheckResult:
    categories = _issue_categories_for_severity(review, severity)
    missing = sorted(set(required_categories) - categories)
    return CheckResult(
        name=f"required_{severity}_qa_categories",
        passed=not missing,
        detail=(
            f"all required {severity} issue categories present"
            if not missing
            else f"missing {severity} categories: {', '.join(missing)}"
        ),
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


def _evidence_ledger_for_fixture(
    fixture: dict[str, Any],
    *,
    source_map: SourceMap,
) -> EvidenceLedger:
    evidence_ledger = EvidenceLedger.model_validate(fixture["evidence_ledger"])
    if "source_fetch_log" in fixture:
        evidence_ledger = validate_evidence(
            evidence_ledger.claims,
            source_map=source_map,
            source_fetch_log=SourceFetchLog.model_validate(fixture["source_fetch_log"]),
        )
    if "charter" in fixture:
        evidence_ledger = enforce_direct_company_evidence(
            evidence_ledger,
            charter=ResearchCharter.model_validate(fixture["charter"]),
            source_map=source_map,
        )
    return evidence_ledger


def _check_evidence_expectations(
    *,
    evidence_ledger: EvidenceLedger,
    expected_evidence: dict[str, Any],
) -> list[CheckResult]:
    if not expected_evidence:
        return []

    claim_ids = {claim.id for claim in evidence_ledger.claims}
    warnings = list(evidence_ledger.validation_warnings)
    checks: list[CheckResult] = []

    if "remaining_claim_ids" in expected_evidence:
        expected_remaining = set(expected_evidence["remaining_claim_ids"])
        checks.append(
            CheckResult(
                name="evidence_remaining_claims",
                passed=claim_ids == expected_remaining,
                detail=(
                    f"actual={sorted(claim_ids)}, "
                    f"expected={sorted(expected_remaining)}"
                ),
            )
        )

    blocked_claim_ids = expected_evidence.get("blocked_claim_ids", [])
    if blocked_claim_ids:
        still_present = sorted(set(blocked_claim_ids) & claim_ids)
        checks.append(
            CheckResult(
                name="evidence_claims_blocked",
                passed=not still_present,
                detail=(
                    "all expected blocked claim IDs were removed"
                    if not still_present
                    else f"blocked claim IDs still present: {', '.join(still_present)}"
                ),
            )
        )

    required_warning_substrings = expected_evidence.get(
        "required_warning_substrings",
        [],
    )
    for index, expected_substring in enumerate(required_warning_substrings, start=1):
        checks.append(
            CheckResult(
                name=(
                    "direct_company_evidence_block"
                    if expected_substring == DIRECT_EVIDENCE_SUFFICIENCY_WARNING
                    else f"evidence_warning_{index}"
                ),
                passed=any(expected_substring in warning for warning in warnings),
                detail=(
                    f"warning present: {expected_substring}"
                    if any(expected_substring in warning for warning in warnings)
                    else f"missing warning containing: {expected_substring}"
                ),
            )
        )

    expected_blocking = expected_evidence.get("expect_blocking_warnings")
    if expected_blocking is not None:
        actual_blocking = has_blocking_evidence_warnings(evidence_ledger)
        checks.append(
            CheckResult(
                name="evidence_blocking_warnings",
                passed=actual_blocking is expected_blocking,
                detail=f"actual={actual_blocking}, expected={expected_blocking}",
            )
        )

    return checks


def evaluate_fixture(fixture: dict[str, Any]) -> FixtureResult:
    fixture_id = fixture["id"]
    name = fixture.get("name", fixture_id)
    source_map = SourceMap.model_validate(fixture["source_map"])
    evidence_ledger = _evidence_ledger_for_fixture(fixture, source_map=source_map)
    report = Report.model_validate(fixture["draft_report"])
    expected_qa = fixture.get("expected_qa", {})
    expected_evidence = fixture.get("expected_evidence", {})

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
        _check_issue_floor(
            review=review,
            severity="high",
            minimum=expected_qa.get("min_high_issues"),
        ),
        _check_issue_limit(
            review=review,
            severity="medium",
            limit=expected_qa.get("max_medium_issues"),
        ),
        _check_issue_floor(
            review=review,
            severity="medium",
            minimum=expected_qa.get("min_medium_issues"),
        ),
        _check_issue_limit(
            review=review,
            severity="low",
            limit=expected_qa.get("max_low_issues"),
        ),
        _check_issue_floor(
            review=review,
            severity="low",
            minimum=expected_qa.get("min_low_issues"),
        ),
    ]
    checks.extend(
        _check_category_expectations(
            review=review,
            required_categories=expected_qa.get("required_categories", []),
            forbidden_categories=expected_qa.get("forbidden_categories", []),
        )
    )
    for severity in ("high", "medium", "low"):
        required_severity_categories = expected_qa.get(
            f"required_{severity}_categories",
            [],
        )
        if required_severity_categories:
            checks.append(
                _check_required_severity_categories(
                    review=review,
                    severity=severity,
                    required_categories=required_severity_categories,
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
    unsupported_details = _issue_details(
        review,
        severity="high",
        categories={"unsupported_claim"},
    )
    checks.append(
        CheckResult(
            name="unsupported_claims",
            passed=(
                (
                    expected_qa.get("max_high_unsupported_claims") is None
                    or high_unsupported
                    <= int(expected_qa["max_high_unsupported_claims"])
                )
                and high_unsupported >= int(expected_qa.get("min_high_unsupported_claims", 0))
            ),
            detail=_detail_or_default(
                unsupported_details,
                f"{high_unsupported} high unsupported-claim issues",
            ),
        )
    )

    grounding_details = _issue_details(
        review,
        severity="high",
        categories={"unsupported_claim", "source_gap"},
    )
    checks.append(
        CheckResult(
            name="source_grounding",
            passed=bool(grounding_details)
            if expected_qa.get("expect_source_grounding_issue", False)
            else not grounding_details,
            detail=_detail_or_default(
                grounding_details,
                "no high-severity grounding issues",
            ),
        )
    )
    checks.extend(
        _check_evidence_expectations(
            evidence_ledger=evidence_ledger,
            expected_evidence=expected_evidence,
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
        evidence_ledger=evidence_ledger,
    )


def load_fixtures(fixtures_dir: Path) -> list[dict[str, Any]]:
    paths = sorted(fixtures_dir.glob("*.json"))
    if not paths:
        raise FileNotFoundError(f"No fixture JSON files found in {fixtures_dir}")
    return [_load_json(path) for path in paths]


def results_to_dict(results: list[FixtureResult]) -> dict[str, Any]:
    passed_count = sum(1 for result in results if result.passed)
    fixture_count = len(results)
    return {
        "fixture_count": fixture_count,
        "passed_count": passed_count,
        "failed_count": fixture_count - passed_count,
        "all_passed": passed_count == fixture_count,
        "rubrics": list(RUBRIC_NAMES),
        "fixtures": [result.to_dict() for result in results],
    }


def render_scorecard(results: list[FixtureResult]) -> str:
    passed_count = sum(1 for result in results if result.passed)
    lines = [
        "# Evaluation Scorecard",
        "",
        f"- Fixtures: {len(results)}",
        f"- Result: {passed_count}/{len(results)} fixtures passed",
        f"- Rubrics: {', '.join(RUBRIC_NAMES)}",
        "",
        "| Fixture | Name | Status | Score | High | Medium | Low |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        lines.append(
            "| "
            f"{result.fixture_id} | {result.name} | {status} | {result.score} | "
            f"{_issue_count(result.qa_review, 'high')} | "
            f"{_issue_count(result.qa_review, 'medium')} | "
            f"{_issue_count(result.qa_review, 'low')} |"
        )

    lines.extend(["", "## Fixture Details"])
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        lines.extend(
            [
                "",
                f"### {result.fixture_id} - {result.name}",
                "",
                f"- Total: {status} ({result.score})",
                "- Checks:",
            ]
        )
        for check in result.checks:
            check_status = "PASS" if check.passed else "FAIL"
            lines.append(f"  - {check.name}: {check_status} - {check.detail}")
        if result.qa_review.issues:
            lines.append("- QA issues:")
            for issue in result.qa_review.issues:
                category = issue.category or "uncategorized"
                lines.append(
                    f"  - {issue.severity}/{category}: {issue.problem} "
                    f"Fix: {issue.suggested_fix}"
                )
        expected_guardrail_checks = [
            check
            for check in result.checks
            if check.name
            in {
                "direct_company_evidence_block",
                "evidence_blocking_warnings",
                "evidence_claims_blocked",
                "evidence_remaining_claims",
                "required_high_qa_categories",
                "required_medium_qa_categories",
            }
        ]
        if expected_guardrail_checks:
            lines.append("- Expected guardrails:")
            for check in expected_guardrail_checks:
                check_status = "PASS" if check.passed else "FAIL"
                lines.append(f"  - {check.name}: {check_status} - {check.detail}")

    lines.extend(["", "## Expected Guardrail Details"])
    for result in results:
        guardrail_details = [
            check.detail
            for check in result.checks
            if check.name
            in {
                "direct_company_evidence_block",
                "evidence_blocking_warnings",
                "evidence_claims_blocked",
                "required_high_qa_categories",
            }
        ]
        if guardrail_details:
            lines.append(f"- {result.fixture_id}: {'; '.join(guardrail_details)}")

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
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help="Optional path to write machine-readable JSON results.",
    )
    args = parser.parse_args(argv)

    results, scorecard = run(args.fixtures_dir)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(scorecard, encoding="utf-8")
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(results_to_dict(results), indent=2) + "\n",
            encoding="utf-8",
        )
    print(scorecard, end="")
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
