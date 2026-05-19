from __future__ import annotations

from agentic_research.evidence_ledger import EvidenceLedger
from agentic_research.models import (
    EvidenceLedger as EvidenceLedgerModel,
    IssueCategory,
    QAIssue,
    QAReview,
    Report,
    Severity,
    SourceMap,
)
from agentic_research.report_validation import validate_report


def _issue_category_for_evidence_warning(warning: str) -> IssueCategory:
    if "source id or URL" in warning:
        return "unsupported_claim"
    if "unknown source id" in warning or "source map URL" in warning:
        return "source_gap"
    if "low-authority" in warning or "authority score" in warning:
        return "weak_source"
    if "near-duplicate" in warning or "duplicate evidence claim id" in warning:
        return "report_structure_issue"
    if "source_metadata_only" in warning or "source_finding_aid" in warning:
        return "weak_source"
    return "unsupported_claim"


def run_deterministic_qa_checks(
    *,
    source_map: SourceMap,
    evidence_ledger: EvidenceLedgerModel,
    draft_report: Report,
    template_name: str | None = None,
) -> QAReview:
    report_review = validate_report(
        draft_report,
        evidence_ledger=evidence_ledger,
        source_map=source_map,
        template_name=template_name,
    )
    issues: list[QAIssue] = list(report_review.issues)

    ledger = EvidenceLedger(evidence_ledger.claims)
    evidence_warnings = ledger.validate(
        source_map=source_map,
    )
    for warning in evidence_warnings:
        severity: Severity = (
            "high"
            if (
                "source id or URL" in warning
                or "unknown source id" in warning
                or "low-authority" in warning
                or "source map URL" in warning
            )
            else "medium"
        )
        issues.append(
            QAIssue(
                severity=severity,
                category=_issue_category_for_evidence_warning(warning),
                problem=warning,
                suggested_fix="Fix the evidence ledger before publishing the report.",
                affected_section="Evidence Ledger",
            )
        )

    return QAReview(
        ready_to_publish=not issues,
        issues=issues,
        summary=(
            "Deterministic QA found no issues."
            if not issues
            else "Deterministic QA found issues."
        ),
    )


def merge_qa_reviews(*reviews: QAReview) -> QAReview:
    issues: list[QAIssue] = []
    summaries: list[str] = []
    for review in reviews:
        issues.extend(review.issues)
        if review.summary:
            summaries.append(review.summary)

    return QAReview(
        ready_to_publish=all(review.ready_to_publish for review in reviews),
        issues=issues,
        summary=" ".join(summaries) if summaries else None,
    )


def has_high_severity_issues(review: QAReview) -> bool:
    return any(issue.severity == "high" for issue in review.issues)
