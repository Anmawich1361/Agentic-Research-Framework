from __future__ import annotations

from agentic_research.evidence_ledger import EvidenceLedger
from agentic_research.models import (
    EvidenceLedger as EvidenceLedgerModel,
    QAIssue,
    QAReview,
    Report,
    Severity,
    SourceMap,
)


def _has_heading(markdown: str, heading: str) -> bool:
    normalized = markdown.lower()
    target = heading.lower()
    return f"## {target}" in normalized or f"# {target}" in normalized


def run_deterministic_qa_checks(
    *,
    source_map: SourceMap,
    evidence_ledger: EvidenceLedgerModel,
    draft_report: Report,
) -> QAReview:
    issues: list[QAIssue] = []
    markdown = draft_report.markdown

    if not _has_heading(markdown, "Source Appendix"):
        issues.append(
            QAIssue(
                severity="medium",
                problem="Report is missing a source appendix section.",
                suggested_fix="Add a Source Appendix section based on the source map.",
                affected_section="Source Appendix",
            )
        )
    if not _has_heading(markdown, "Risks"):
        issues.append(
            QAIssue(
                severity="medium",
                problem="Report is missing a risks section.",
                suggested_fix="Add a Risks section with evidence-backed caveats.",
                affected_section="Risks",
            )
        )
    if not _has_heading(markdown, "Open Questions"):
        issues.append(
            QAIssue(
                severity="medium",
                problem="Report is missing an open questions section.",
                suggested_fix="Add Open Questions that identify unresolved research gaps.",
                affected_section="Open Questions",
            )
        )

    ledger = EvidenceLedger(evidence_ledger.claims)
    evidence_warnings = ledger.validate(
        source_scores={score.source_id: score for score in source_map.scores}
    )
    for warning in evidence_warnings:
        severity: Severity = (
            "high" if "source id or URL" in warning or "low-authority" in warning else "medium"
        )
        issues.append(
            QAIssue(
                severity=severity,
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
