from __future__ import annotations

from agentic_research.models import (
    EvidenceClaim,
    EvidenceLedger as EvidenceLedgerModel,
    Report,
    ResearchCharter,
    ResearchPlan,
    SourceCandidate,
    SourceFetchLog,
    SourceMap,
)
from agentic_research.report_validation import (
    missing_report_sections,
    required_sections_for_report,
)
from agentic_research.report_writer import render_source_appendix
from agentic_research.report_writer import select_report_template_name


_CONSERVATIVE_REPORT_EXCLUDE_MARKERS = (
    "current",
    "recent",
    "latest",
    "2025",
    "earnings",
    "transcript",
    "strategic",
    "strategy",
    "priorit",
    "momentum",
    "technology investment",
    "warehouse opening",
    "e-commerce",
    "tariff",
    "renewal rate",
)

_CONSERVATIVE_REPORT_SOURCE_TYPES = {
    "corporate_filing",
    "earnings_release",
    "investor_material",
    "primary_company",
}


def _unique_nonempty(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_items: list[str] = []
    for item in items:
        normalized = item.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_items.append(normalized)
    return unique_items


def _format_markdown_bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _source_id_count(evidence_ledger: EvidenceLedgerModel) -> int:
    return len(
        {
            claim.source_id
            for claim in evidence_ledger.claims
            if claim.source_id is not None and claim.source_id.strip()
        }
    )


def _claim_reference_rules(evidence_ledger: EvidenceLedgerModel) -> list[str]:
    allowed_count = len(evidence_ledger.claims)
    return [
        "Every material factual report statement must cite a claim ID from "
        "allowed_claim_ids in [claim_id] form.",
        "Use only allowed_claim_ids; do not invent, reuse, or restore dropped "
        "claim IDs.",
        "allowed_claim_ids are exact, case-sensitive strings. If a numeric "
        "sequence skips an ID, the skipped ID is not allowed.",
        "Do not cite claim IDs from specialist_analyses unless that exact ID "
        "is present in allowed_claim_ids.",
        "specialist_analyses in this payload are filtered for synthesis; the "
        "final evidence_ledger and allowed_claim_ids are authoritative.",
        "If a point would require a missing claim ID, omit it or rephrase it "
        "as an open question or evidence gap.",
        "Populate claim_ids with every allowed claim ID cited in markdown.",
        "Before returning, compare every bracketed claim ID in markdown and "
        "every item in claim_ids against allowed_claim_ids; remove or rewrite "
        "anything that does not match exactly.",
        f"The final evidence ledger currently contains {allowed_count} allowed claim IDs.",
    ]


def _synthesis_quality_rules() -> list[str]:
    return [
        "Use source_content-derived evidence claims as the basis for report claims.",
        "Do not promote CNBC/news summaries, transcript summaries, or source-finding "
        "aids into target company strategy unless a concrete evidence claim directly "
        "supports that strategy statement.",
        "Recent developments must cite direct evidence claims from fetched source "
        "content. If latest earnings release or transcript support is missing, say "
        "that it was not verified from available sources.",
        "Supplier-meeting recommendations require direct claim IDs or an explicit "
        "caveat that the point is a hypothesis or question to confirm with the target company.",
        "Separate directly supported facts, cautious inferences, and unknowns/open "
        "questions in the draft.",
        "Quartr pages, source-finding aids, search-result pages, and source-map "
        "rationales are not strategic evidence.",
    ]


def _section_fill_lines(
    section: str,
    *,
    plan: ResearchPlan,
    source_map: SourceMap,
    evidence_ledger: EvidenceLedgerModel,
) -> list[str]:
    open_questions = _unique_nonempty(
        [
            *plan.checkpoint_questions,
            *source_map.gaps,
            *plan.data_gaps,
        ]
    )
    evidence_lines = [
        f"{claim.claim} [{claim.id}]" for claim in evidence_ledger.claims[:5]
    ]
    risk_lines = _unique_nonempty([*plan.known_risks, *source_map.gaps])

    if section == "What We Know":
        return evidence_lines or [
            "No directly supported facts were available in the evidence ledger."
        ]
    if section in {"What We Do Not Know", "Open Questions"}:
        return open_questions or [
            "No open questions were identified from checkpoint questions, "
            "source-map gaps, or plan data gaps."
        ]
    if section == "Questions to Ask":
        return plan.checkpoint_questions or [
            "Ask which unanswered research gaps matter most for the meeting."
        ]
    if section in {"Risks", "Risks and Watchouts"}:
        return risk_lines or [
            "Risk assessment is limited by the available evidence set."
        ]
    if section == "Evidence Limitations":
        claim_count = len(evidence_ledger.claims)
        source_count = _source_id_count(evidence_ledger)
        return [
            (
                f"Evidence is thin: {claim_count} evidence claims across "
                f"{source_count} source IDs."
            ),
            "Treat unsupported conclusions as open questions until more sources are added.",
        ]
    if section == "Source Appendix":
        return []
    if section in {"Business Overview", "Industry Definition"}:
        return evidence_lines or [
            "No evidence-backed overview was available for this section."
        ]
    if section in {
        "Context for Meeting",
        "Supplier/Buyer Angle",
        "Market Context",
        "Competitive Landscape",
        "Recent Developments",
        "Value Chain",
        "Key Players",
        "Demand Drivers",
    }:
        return [
            "No direct evidence-backed content was available for this section; "
            "treat it as an open question."
        ]
    return [
        "No evidence-backed content was available for this required section."
    ]


def _repair_missing_report_sections(
    report: Report,
    *,
    plan: ResearchPlan,
    source_map: SourceMap,
    evidence_ledger: EvidenceLedgerModel,
    template_name: str | None,
) -> Report:
    missing = missing_report_sections(
        report,
        template_name=template_name,
        evidence_ledger=evidence_ledger,
        source_map=source_map,
    )
    if not missing:
        return report

    sections: list[str] = []
    for section in missing:
        if section == "Source Appendix":
            source_appendix = render_source_appendix(source_map)
            if source_appendix.startswith("# "):
                source_appendix = f"#{source_appendix}"
            sections.append(source_appendix.rstrip())
            continue
        lines = _section_fill_lines(
            section,
            plan=plan,
            source_map=source_map,
            evidence_ledger=evidence_ledger,
        )
        sections.append(f"## {section}\n{_format_markdown_bullets(lines)}")

    markdown = f"{report.markdown.rstrip()}\n\n" + "\n\n".join(sections) + "\n"
    return report.model_copy(update={"markdown": markdown})


def _claim_line(claim: EvidenceClaim) -> str:
    return f"{claim.claim} [{claim.id}]"


def _evidence_source_ids(evidence_ledger: EvidenceLedgerModel) -> list[str]:
    seen: set[str] = set()
    source_ids: list[str] = []
    for claim in evidence_ledger.claims:
        source_id = (claim.source_id or "").strip()
        if source_id and source_id not in seen:
            seen.add(source_id)
            source_ids.append(source_id)
    return source_ids


def _is_conservative_report_claim(
    claim: EvidenceClaim,
    *,
    source_lookup: dict[str, SourceCandidate],
) -> bool:
    source = source_lookup.get(claim.source_id or "")
    source_type = (claim.source_type or (source.source_type if source else "")).lower()
    if source_type not in _CONSERVATIVE_REPORT_SOURCE_TYPES:
        return False
    if claim.claim_type != "fact":
        return False
    claim_text = f"{claim.claim} {claim.report_section}".lower()
    return not any(marker in claim_text for marker in _CONSERVATIVE_REPORT_EXCLUDE_MARKERS)


def _conservative_report_claims(
    evidence_ledger: EvidenceLedgerModel,
    *,
    source_map: SourceMap,
) -> list[EvidenceClaim]:
    source_lookup = {source.id: source for source in source_map.sources}
    return [
        claim
        for claim in evidence_ledger.claims
        if _is_conservative_report_claim(claim, source_lookup=source_lookup)
    ]


def _source_ids_for_claims(claims: list[EvidenceClaim]) -> list[str]:
    seen: set[str] = set()
    source_ids: list[str] = []
    for claim in claims:
        source_id = (claim.source_id or "").strip()
        if source_id and source_id not in seen:
            seen.add(source_id)
            source_ids.append(source_id)
    return source_ids


def _supplier_claims(claims: list[EvidenceClaim]) -> list[EvidenceClaim]:
    supplier_markers = ("supplier", "vendor")
    return [
        claim
        for claim in claims
        if any(
            marker in f"{claim.claim} {claim.report_section} {claim.source_type or ''}".lower()
            for marker in supplier_markers
        )
    ]


def _claim_reference_text(claims: list[EvidenceClaim]) -> str:
    return " ".join(f"[{claim.id}]" for claim in claims).strip()


def _conservative_source_appendix(
    source_map: SourceMap,
    *,
    source_ids: list[str],
) -> str:
    source_lookup = {source.id: source for source in source_map.sources}
    rows: list[str] = []
    for source_id in source_ids:
        source = source_lookup.get(source_id)
        if source is None:
            continue
        rows.append(f"- {source.id} - {source.title} - {source.url}")
    return "\n".join(rows) or "- No cited evidence sources were available."


def _conservative_evidence_limitations(
    *,
    evidence_ledger: EvidenceLedgerModel,
    cited_claims: list[EvidenceClaim],
    source_fetch_log: SourceFetchLog | None,
) -> list[str]:
    source_count = len(_source_ids_for_claims(cited_claims))
    lines = [
        (
            f"This report uses {len(cited_claims)} evidence claims "
            f"from {source_count} cited source IDs."
        )
    ]
    if source_fetch_log is not None:
        failed_or_skipped_count = sum(
            1 for result in source_fetch_log.results if result.status in {"failed", "skipped"}
        )
        if failed_or_skipped_count:
            lines.append(
                "Some discovered investor, earnings, filing, or news sources were not "
                "verified from fetched source content."
            )
    lines.append(
        "Treat uncited supplier priorities, category fit, buyer identity, and timing as "
        "questions to confirm."
    )
    return lines


def _create_conservative_report(
    *,
    charter: ResearchCharter,
    plan: ResearchPlan,
    source_map: SourceMap,
    evidence_ledger: EvidenceLedgerModel,
    source_fetch_log: SourceFetchLog | None,
) -> Report:
    target = charter.target.strip() or "the target company"
    template_name = select_report_template_name(charter)
    required_sections = required_sections_for_report(
        template_name=template_name,
        evidence_ledger=evidence_ledger,
        source_map=source_map,
    )
    conservative_claims = _conservative_report_claims(
        evidence_ledger,
        source_map=source_map,
    )
    direct_claims = conservative_claims[:6]
    first_claims = direct_claims[:3]
    supplier_claims = _supplier_claims(conservative_claims)[:3]
    angle_claims = supplier_claims or first_claims
    cited_claims: list[EvidenceClaim] = []
    seen_claim_ids: set[str] = set()
    for claim in [*first_claims, *direct_claims, *angle_claims]:
        if claim.id in seen_claim_ids:
            continue
        cited_claims.append(claim)
        seen_claim_ids.add(claim.id)
    source_ids = _source_ids_for_claims(cited_claims) or _evidence_source_ids(evidence_ledger)
    claim_ids = [claim.id for claim in cited_claims]
    open_questions = _unique_nonempty(
        [
            *plan.checkpoint_questions,
            *source_map.gaps,
            *plan.data_gaps,
        ]
    )
    evidence_limitations = _conservative_evidence_limitations(
        evidence_ledger=evidence_ledger,
        cited_claims=cited_claims,
        source_fetch_log=source_fetch_log,
    )
    section_lines: dict[str, list[str]] = {
        "Executive Summary": [
            (
                "Available fetched evidence supports only a narrow supplier-meeting "
                f"brief based on directly cited public {target} evidence."
            ),
            (
                "Do not treat this as verification of latest results, management "
                "commentary, current momentum, or category-specific buying criteria."
            ),
            *[_claim_line(claim) for claim in first_claims],
        ],
        "Context for Meeting": [
            (
                "Use this as a narrow source-grounded prep note, not as a full account "
                f"of {target} category or buying priorities."
            ),
            (
                "Latest earnings, transcript, or results-release support was not "
                "verified from fetched source content."
            ),
        ],
        "What We Know": [_claim_line(claim) for claim in direct_claims]
        or ["No directly supported facts were available."],
        "What We Do Not Know": open_questions
        or ["The available evidence does not identify category-specific buyer priorities."],
        "Supplier/Buyer Angle": [
            (
                "Hypothesis to confirm: prepare the meeting around the public facts "
                "that are directly cited here, not around uncited buying-priority "
                f"claims. {_claim_reference_text(angle_claims)}"
            ).strip(),
            (
                "Hypothesis to confirm: supplier recommendations should stay conditional "
                f"until the buyer at {target} confirms category, geography, timing, and decision "
                "criteria."
            ),
        ],
        "Questions to Ask": plan.checkpoint_questions
        or ["Which category, buyer function, geography, and timing should this brief cover?"],
        "Risks and Watchouts": [
            "Public evidence may not reflect the relevant category, buyer, or geography.",
            f"Unsupported recommendations should remain questions until {target} confirms them.",
        ],
        "Evidence Limitations": evidence_limitations,
        "Source Appendix": [],
    }

    title = f"# Meeting Prep Brief: {charter.target}"
    sections: list[str] = [title]
    for section in required_sections:
        if section == "Source Appendix":
            sections.append(
                f"## Source Appendix\n{_conservative_source_appendix(source_map, source_ids=source_ids)}"
            )
            continue
        lines = section_lines.get(
            section,
            _section_fill_lines(
                section,
                plan=plan,
                source_map=source_map,
                evidence_ledger=evidence_ledger,
            ),
        )
        sections.append(f"## {section}\n{_format_markdown_bullets(lines)}")
    if "Evidence Limitations" not in required_sections:
        sections.append(
            "## Evidence Limitations\n"
            f"{_format_markdown_bullets(evidence_limitations)}"
        )

    return Report(
        title=f"{charter.target} Meeting Prep Brief",
        markdown="\n\n".join(section.rstrip() for section in sections) + "\n",
        source_ids=source_ids,
        claim_ids=claim_ids,
        status="draft",
    )


def _can_apply_supplier_meeting_fallback(charter: ResearchCharter) -> bool:
    deliverable = charter.deliverable.lower()
    return select_report_template_name(charter) == "meeting_prep.md" and "meeting" in deliverable

claim_reference_rules = _claim_reference_rules
synthesis_quality_rules = _synthesis_quality_rules
repair_missing_report_sections = _repair_missing_report_sections
create_conservative_report = _create_conservative_report
can_apply_supplier_meeting_fallback = _can_apply_supplier_meeting_fallback

__all__ = [
    "can_apply_supplier_meeting_fallback",
    "claim_reference_rules",
    "create_conservative_report",
    "repair_missing_report_sections",
    "synthesis_quality_rules",
]
