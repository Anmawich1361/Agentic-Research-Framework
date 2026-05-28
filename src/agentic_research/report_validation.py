from __future__ import annotations

import re

from agentic_research.models import (
    EvidenceLedger,
    IssueCategory,
    QAIssue,
    QAReview,
    Report,
    Severity,
    SourceMap,
)


TEMPLATE_REQUIRED_SECTIONS: dict[str, list[str]] = {
    "meeting_prep.md": [
        "Executive Summary",
        "Context for Meeting",
        "What We Know",
        "What We Do Not Know",
        "Supplier/Buyer Angle",
        "Questions to Ask",
        "Risks and Watchouts",
        "Source Appendix",
    ],
    "company_brief.md": [
        "Executive Summary",
        "Business Overview",
        "Market Context",
        "Competitive Landscape",
        "Recent Developments",
        "Risks",
        "Open Questions",
        "Source Appendix",
    ],
    "investment_memo.md": [
        "Executive Summary",
        "Business Overview",
        "Market / Industry Context",
        "Business Model",
        "Financial and Operating Profile",
        "Competitive Landscape",
        "Growth Drivers",
        "Risks",
        "Open Diligence Questions",
        "Source Appendix",
    ],
    "industry_primer.md": [
        "Executive Summary",
        "Industry Definition",
        "Value Chain",
        "Key Players",
        "Demand Drivers",
        "Risks",
        "Open Questions",
        "Source Appendix",
    ],
}

GENERIC_REQUIRED_SECTIONS = [
    "Source Appendix",
    "Risks",
    "Open Questions",
]

THIN_EVIDENCE_MIN_CLAIMS = 3
THIN_EVIDENCE_MIN_SOURCE_IDS = 2

_BRACKET_REFERENCE_RE = re.compile(r"\[([A-Za-z][A-Za-z0-9_-]*)\](?!\()")
_CLAIM_IDS_FOOTER_RE = re.compile(r"(?im)^Claim IDs cited:\s*(.+)$")
_LIKELY_CLAIM_ID_RE = re.compile(
    r"^(?:claim_[A-Za-z0-9_-]+|specialist_[A-Za-z0-9_-]+|[A-Za-z]+\d+)$"
)
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_SOURCE_ID_REFERENCE_RE = re.compile(r"\b(src_[A-Za-z0-9_-]+)\b")
_LIKELY_SOURCE_ID_RE = re.compile(r"^(?:src_[A-Za-z0-9_-]+|s\d+)$")
_LIKELY_SOURCE_ID_TOKEN_RE = re.compile(r"\b(?:src_[A-Za-z0-9_-]+|s\d+)\b")
_BROAD_UNSUPPORTED_MARKERS = (
    "advantage",
    "best positioned",
    "critical",
    "differentiated",
    "dominates",
    "durable",
    "leading",
    "market leader",
    "must",
    "robust",
    "strong",
    "strategic priority",
    "will",
)
_BROAD_CLAIM_SKIP_SECTIONS = {
    "evidence limitations",
    "open questions",
    "questions to ask",
    "source appendix",
    "what we do not know",
}
_CAVEAT_MARKERS = (
    "available sources do not",
    "caveat",
    "checked against",
    "could not verify",
    "evidence gap",
    "hypothesis",
    "limited public evidence",
    "not found",
    "not surfaced",
    "not verified",
    "open question",
    "treat",
    "unknown",
    "verify",
)
_RECENT_CLAIM_MARKERS = (
    "current",
    "digital",
    "earnings",
    "e-commerce",
    "latest",
    "quarter",
    "recent",
    "same-store",
    "strategic",
    "strategy",
    "tariff",
)
_RECOMMENDATION_MARKERS = (
    "emphasize",
    "must",
    "need to",
    "prioritize",
    "recommend",
    "should",
    "stronger pitch",
)
_SOURCE_FINDING_AID_MARKERS = (
    "finder",
    "finding aid",
    "find transcript",
    "quartr",
    "source_finding_aid",
    "useful for finding",
)
_QUALITY_SKIP_SECTIONS = {
    "evidence limitations",
    "questions to ask",
    "source appendix",
    "what we do not know",
}


class ReportSectionValidationError(ValueError):
    def __init__(
        self,
        missing_sections: list[str] | None = None,
        *,
        message: str | None = None,
    ) -> None:
        self.missing_sections = missing_sections or []
        if message is None:
            message = (
                "Report is missing required sections: "
                f"{', '.join(self.missing_sections)}"
            )
        super().__init__(message)


def _template_key(template_name: str | None) -> str | None:
    if template_name is None:
        return None
    return template_name if template_name.endswith(".md") else f"{template_name}.md"


def _normalize_heading(heading: str) -> str:
    normalized = heading.strip().strip("#").strip()
    normalized = normalized.strip(":")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.lower()


def report_heading_titles(markdown: str) -> set[str]:
    return {_normalize_heading(match) for match in _HEADING_RE.findall(markdown)}


def has_heading(markdown: str, heading: str) -> bool:
    return _normalize_heading(heading) in report_heading_titles(markdown)


def required_sections_for_template(template_name: str | None) -> list[str]:
    template_key = _template_key(template_name)
    if template_key is None:
        return list(GENERIC_REQUIRED_SECTIONS)
    return list(TEMPLATE_REQUIRED_SECTIONS.get(template_key, GENERIC_REQUIRED_SECTIONS))


def is_thin_evidence(
    evidence_ledger: EvidenceLedger | None,
    source_map: SourceMap | None = None,
) -> bool:
    if evidence_ledger is None:
        return False

    claim_count = len(evidence_ledger.claims)
    source_ids = {
        claim.source_id
        for claim in evidence_ledger.claims
        if claim.source_id is not None and claim.source_id.strip()
    }
    if not source_ids and source_map is not None:
        source_ids = {
            score.source_id
            for score in source_map.scores
            if score.include and score.source_id.strip()
        }
    return (
        claim_count < THIN_EVIDENCE_MIN_CLAIMS
        or len(source_ids) < THIN_EVIDENCE_MIN_SOURCE_IDS
    )


def required_sections_for_report(
    *,
    template_name: str | None,
    evidence_ledger: EvidenceLedger | None = None,
    source_map: SourceMap | None = None,
) -> list[str]:
    required_sections = required_sections_for_template(template_name)
    if (
        is_thin_evidence(evidence_ledger, source_map)
        and "Evidence Limitations" not in required_sections
    ):
        required_sections = [*required_sections, "Evidence Limitations"]
    return required_sections


def missing_report_sections(
    report: Report,
    *,
    template_name: str | None = None,
    evidence_ledger: EvidenceLedger | None = None,
    source_map: SourceMap | None = None,
) -> list[str]:
    headings = report_heading_titles(report.markdown)
    return [
        section
        for section in required_sections_for_report(
            template_name=template_name,
            evidence_ledger=evidence_ledger,
            source_map=source_map,
        )
        if _normalize_heading(section) not in headings
    ]


def _known_id_references(line: str, known_ids: set[str]) -> set[str]:
    return {
        known_id
        for known_id in known_ids
        if re.search(
            rf"(?<![A-Za-z0-9_-]){re.escape(known_id)}(?![A-Za-z0-9_-])",
            line,
        )
    }


def markdown_source_references(
    markdown: str,
    known_source_ids: set[str] | None = None,
) -> set[str]:
    references = set(_SOURCE_ID_REFERENCE_RE.findall(markdown))
    known_source_ids = known_source_ids or set()
    current_section: str | None = None
    for line in markdown.splitlines():
        current_section = _current_section(line, current_section)
        if current_section != "source appendix":
            continue
        references.update(_LIKELY_SOURCE_ID_TOKEN_RE.findall(line))
        references.update(_known_id_references(line, known_source_ids))
        references.update(
            reference
            for reference in _BRACKET_REFERENCE_RE.findall(line)
            if reference in known_source_ids or _LIKELY_SOURCE_ID_RE.match(reference)
        )
    return references


def markdown_claim_references(
    markdown: str,
    known_claim_ids: set[str],
    *,
    known_source_ids: set[str] | None = None,
) -> set[str]:
    source_references = markdown_source_references(
        markdown,
        known_source_ids=known_source_ids,
    )
    references = set(_BRACKET_REFERENCE_RE.findall(markdown))
    for footer_match in _CLAIM_IDS_FOOTER_RE.findall(markdown):
        references.update(
            reference.strip().strip(".,;")
            for reference in re.split(r"[\s,]+", footer_match)
        )
    return {
        reference
        for reference in references
        if reference in known_claim_ids
        or (_LIKELY_CLAIM_ID_RE.match(reference) and reference not in source_references)
    }


def validate_report_traceability(
    report: Report,
    *,
    evidence_ledger: EvidenceLedger,
    source_map: SourceMap,
) -> None:
    allowed_claim_ids = {claim.id for claim in evidence_ledger.claims}
    allowed_source_ids = {source.id for source in source_map.sources}
    markdown_claim_ids = markdown_claim_references(
        report.markdown,
        allowed_claim_ids,
        known_source_ids=allowed_source_ids,
    )
    report.claim_ids = sorted(set(report.claim_ids).union(markdown_claim_ids))
    unknown_claim_ids = sorted(
        claim_id for claim_id in report.claim_ids if claim_id not in allowed_claim_ids
    )
    if unknown_claim_ids:
        raise ReportSectionValidationError(
            message=(
                "Report contains unknown evidence claim references: "
                f"{', '.join(unknown_claim_ids)}"
            )
        )

    report_source_ids = set(report.source_ids).union(
        markdown_source_references(report.markdown, known_source_ids=allowed_source_ids)
    )
    unknown_source_ids = sorted(
        source_id for source_id in report_source_ids if source_id not in allowed_source_ids
    )
    if unknown_source_ids:
        raise ReportSectionValidationError(
            message=(
                "Report contains unknown source references: "
                f"{', '.join(unknown_source_ids)}"
            )
        )


def validate_report_sections(
    report: Report,
    *,
    template_name: str | None = None,
    evidence_ledger: EvidenceLedger | None = None,
    source_map: SourceMap | None = None,
) -> None:
    missing = missing_report_sections(
        report,
        template_name=template_name,
        evidence_ledger=evidence_ledger,
        source_map=source_map,
    )
    if missing:
        raise ReportSectionValidationError(missing)


def _current_section(line: str, current: str | None) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("#"):
        return current
    return _normalize_heading(stripped.lstrip("#").strip())


def _line_has_claim_reference(line: str) -> bool:
    return "[" in line and "]" in line


def _contains_broad_marker(text: str) -> bool:
    lowered = text.lower()
    for marker in _BROAD_UNSUPPORTED_MARKERS:
        if " " in marker:
            if marker in lowered:
                return True
        elif re.search(rf"\b{re.escape(marker)}\b", lowered):
            return True
    return False


def _contains_any_marker(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def _has_caveat(text: str) -> bool:
    return _contains_any_marker(text, _CAVEAT_MARKERS)


def _line_claim_ids(line: str, known_claim_ids: set[str]) -> set[str]:
    return markdown_claim_references(line, known_claim_ids)


def _source_by_id(source_map: SourceMap) -> dict[str, object]:
    return {source.id: source for source in source_map.sources}


def _is_source_finding_aid(source: object | None) -> bool:
    if source is None:
        return False
    values = [
        getattr(source, "source_type", ""),
        getattr(source, "title", ""),
        getattr(source, "publisher", ""),
        getattr(source, "url", ""),
        getattr(source, "relevance_rationale", ""),
        " ".join(getattr(source, "recommended_uses", []) or []),
    ]
    return _contains_any_marker(" ".join(values), _SOURCE_FINDING_AID_MARKERS)


def _claim_is_direct_evidence(claim: object | None, source: object | None) -> bool:
    if claim is None or _is_source_finding_aid(source):
        return False
    claim_type = getattr(claim, "claim_type", None)
    quote = getattr(claim, "quote_or_excerpt", None)
    return claim_type == "fact" and bool(quote and quote.strip())


def _source_has_publication_date(source: object | None) -> bool:
    if source is None:
        return False
    publication_date = getattr(source, "publication_date", None)
    return bool(isinstance(publication_date, str) and publication_date.strip())


def _line_is_report_content(line: str) -> bool:
    stripped = line.strip().lstrip("-* ").strip()
    return bool(stripped) and not stripped.startswith("#") and not stripped.endswith("?")


def evidence_bound_quality_issues(
    markdown: str,
    *,
    evidence_ledger: EvidenceLedger,
    source_map: SourceMap,
) -> list[QAIssue]:
    known_claim_ids = {claim.id for claim in evidence_ledger.claims}
    claims_by_id = {claim.id: claim for claim in evidence_ledger.claims}
    sources_by_id = _source_by_id(source_map)
    issues: list[QAIssue] = []
    section: str | None = None

    for line in markdown.splitlines():
        section = _current_section(line, section)
        if section in _QUALITY_SKIP_SECTIONS or not _line_is_report_content(line):
            continue
        claim_ids = _line_claim_ids(line, known_claim_ids)
        claims = [claims_by_id[claim_id] for claim_id in claim_ids if claim_id in claims_by_id]
        sources = [sources_by_id.get(claim.source_id or "") for claim in claims]
        line_text = line.strip().lstrip("-* ").strip()
        has_caveat = _has_caveat(line_text)

        if claim_ids and any(_is_source_finding_aid(source) for source in sources):
            issues.append(
                QAIssue(
                    severity="high",
                    category="weak_source",
                    problem=(
                        "Report promotes a source-finding aid into a strategic "
                        f"conclusion: {line_text}"
                    ),
                    suggested_fix=(
                        "Use source-finding aids only to locate direct evidence; "
                        "do not cite them as strategic support."
                    ),
                    affected_section=section.title() if section else None,
                )
            )
            continue

        if _contains_any_marker(line_text, _RECENT_CLAIM_MARKERS) and not has_caveat:
            direct_recent_sources = [
                source
                for claim, source in zip(claims, sources, strict=False)
                if _claim_is_direct_evidence(claim, source)
            ]
            if not direct_recent_sources:
                issues.append(
                    QAIssue(
                        severity="high",
                        category="missing_recent_signal",
                        problem=(
                            "Recent developments or current strategy are presented "
                            "without concrete evidence from available source content: "
                            f"{line_text}"
                        ),
                        suggested_fix=(
                            "Cite a direct evidence claim from fetched source content "
                            "or state that recent support was not verified."
                        ),
                        affected_section=section.title() if section else None,
                    )
                )
                continue
            if not any(_source_has_publication_date(source) for source in direct_recent_sources):
                issues.append(
                    QAIssue(
                        severity="medium",
                        category="stale_or_unclear_recency",
                        problem=(
                            "Recent developments or current strategy are tied to "
                            "direct evidence, but the cited source has no visible "
                            f"publication date: {line_text}"
                        ),
                        suggested_fix=(
                            "Cite dated source evidence or state that the timing "
                            "of the source could not be verified."
                        ),
                        affected_section=section.title() if section else None,
                    )
                )

        if (
            section == "supplier/buyer angle"
            and _contains_any_marker(line_text, _RECOMMENDATION_MARKERS)
            and not claim_ids
            and not has_caveat
        ):
            issues.append(
                QAIssue(
                    severity="medium",
                    category="overconfident_inference",
                    problem=(
                        "supplier-meeting recommendation lacks direct claim IDs "
                        f"or an explicit caveat: {line_text}"
                    ),
                    suggested_fix=(
                        "Cite direct evidence for the recommendation or frame it "
                        "as a hypothesis to confirm in the meeting."
                    ),
                    affected_section=section.title(),
                )
            )

    return issues


def _is_uncited_broad_claim(line: str) -> bool:
    stripped = line.strip().lstrip("-* ").strip()
    if not stripped or stripped.startswith("#") or _line_has_claim_reference(stripped):
        return False
    return _contains_broad_marker(stripped)


def unsupported_broad_claim_issues(markdown: str) -> list[QAIssue]:
    issues: list[QAIssue] = []
    section: str | None = None
    for line in markdown.splitlines():
        section = _current_section(line, section)
        if section in _BROAD_CLAIM_SKIP_SECTIONS:
            continue
        if not _is_uncited_broad_claim(line):
            continue
        claim_text = line.strip().lstrip("-* ").strip()
        issues.append(
            QAIssue(
                severity="high",
                category="unsupported_claim",
                problem=(
                    "Report contains an uncited broad claim that should be tied "
                    f"to evidence or reframed as an open question: {claim_text}"
                ),
                suggested_fix=(
                    "Cite a specific evidence ledger claim, caveat the statement "
                    "as an inference, or remove it."
                ),
                affected_section=section.title() if section else None,
            )
        )
    return issues


def _issue_for_missing_section(section: str) -> QAIssue:
    category: IssueCategory = "report_structure_issue"
    problem = f"Report is missing required section: {section}."
    suggested_fix = f"Add a {section} section using only evidence-backed content."

    if section == "Source Appendix":
        problem = "Report is missing a source appendix section."
        suggested_fix = "Add a Source Appendix section based on the source map."
    elif section == "Risks":
        problem = "Report is missing a risks section."
        suggested_fix = "Add a Risks section with evidence-backed caveats."
    elif section == "Open Questions":
        problem = "Report is missing an open questions section."
        suggested_fix = "Add Open Questions that identify unresolved research gaps."
    elif section == "Evidence Limitations":
        category = "source_gap"
        problem = (
            "Report is missing an Evidence Limitations section despite thin evidence."
        )
        suggested_fix = (
            "Add Evidence Limitations that names the claim count, source count, "
            "and gaps that constrain the report."
        )

    return QAIssue(
        severity="medium",
        category=category,
        problem=problem,
        suggested_fix=suggested_fix,
        affected_section=section,
    )


def _traceability_issue(error: ReportSectionValidationError) -> QAIssue:
    problem = str(error)
    category: IssueCategory = (
        "source_gap" if "source references" in problem else "unsupported_claim"
    )
    severity: Severity = "high"
    return QAIssue(
        severity=severity,
        category=category,
        problem=problem,
        suggested_fix=(
            "Use only source IDs from the source map and claim IDs from the "
            "evidence ledger."
        ),
        affected_section="Report Traceability",
    )


def validate_report(
    report: Report,
    *,
    evidence_ledger: EvidenceLedger,
    source_map: SourceMap,
    template_name: str | None = None,
) -> QAReview:
    issues = [
        _issue_for_missing_section(section)
        for section in missing_report_sections(
            report,
            template_name=template_name,
            evidence_ledger=evidence_ledger,
            source_map=source_map,
        )
    ]

    try:
        validate_report_traceability(
            report,
            evidence_ledger=evidence_ledger,
            source_map=source_map,
        )
    except ReportSectionValidationError as exc:
        issues.append(_traceability_issue(exc))

    issues.extend(unsupported_broad_claim_issues(report.markdown))
    issues.extend(
        evidence_bound_quality_issues(
            report.markdown,
            evidence_ledger=evidence_ledger,
            source_map=source_map,
        )
    )

    return QAReview(
        ready_to_publish=not issues,
        issues=issues,
        summary=(
            "Report validation found no issues."
            if not issues
            else "Report validation found issues."
        ),
    )
