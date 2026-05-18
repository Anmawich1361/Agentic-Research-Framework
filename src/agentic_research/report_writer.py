from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agentic_research.models import EvidenceLedger, Report, ResearchCharter, ResearchPlan, SourceMap
from agentic_research.settings import TEMPLATES_DIR


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def write_json_artifact(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_template(template_name: str) -> str:
    name = template_name if template_name.endswith(".md") else f"{template_name}.md"
    path = TEMPLATES_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {path}")
    return path.read_text(encoding="utf-8")


def select_report_template_name(charter: ResearchCharter) -> str:
    deliverable = charter.deliverable.lower()
    if "meeting" in deliverable or charter.research_lens == "sales":
        return "meeting_prep.md"
    if "investment" in deliverable or charter.research_lens == "investment":
        return "investment_memo.md"
    if (
        "industry" in deliverable
        or charter.research_lens == "industry"
        or charter.target_type in {"industry", "market"}
    ):
        return "industry_primer.md"
    return "company_brief.md"


def render_markdown_template(template: str, context: dict[str, Any]) -> str:
    rendered = template
    for key, value in context.items():
        rendered = rendered.replace(f"{{{{ {key} }}}}", str(value))
    return rendered


def _bullets(items: list[str]) -> str:
    if not items:
        return "- None identified in Phase 1 mock mode."
    return "\n".join(f"- {item}" for item in items)


def _format_source_map(source_map: SourceMap) -> str:
    source_lookup = {source.id: source for source in source_map.sources}
    lines: list[str] = []
    for score in source_map.scores:
        source = source_lookup[score.source_id]
        include_text = "include" if score.include else "hold"
        lines.append(
            "- "
            f"{source.title} ({source.source_type}) - score {score.final_score}, "
            f"{include_text}; uses: {', '.join(source.recommended_uses)}"
        )
    return "\n".join(lines)


def _table_cell(value: str | None) -> str:
    return (value or "").replace("|", "\\|")


def render_checkpoint(
    charter: ResearchCharter,
    plan: ResearchPlan,
    source_map: SourceMap,
) -> str:
    template = load_template("checkpoint.md")
    return render_markdown_template(
        template,
        {
            "target": charter.target,
            "target_type": charter.target_type,
            "research_lens": charter.research_lens,
            "depth": charter.depth,
            "geography": charter.geography,
            "time_horizon": charter.time_horizon,
            "deliverable": charter.deliverable,
            "research_questions": _bullets(plan.research_questions),
            "source_map": _format_source_map(source_map),
            "early_read": (
                "Mock mode produced a deterministic source map for user steering. "
                "No live research or model synthesis has been run."
            ),
            "gaps_and_caveats": _bullets(source_map.gaps + plan.data_gaps),
            "recommended_direction": (
                "Confirm the target, lens, source priorities, and missing context before "
                "Phase 2 adds live agent checkpointing."
            ),
            "checkpoint_questions": _bullets(plan.checkpoint_questions),
        },
    )


def write_checkpoint(
    run_dir: Path,
    charter: ResearchCharter,
    plan: ResearchPlan,
    source_map: SourceMap,
) -> Path:
    checkpoint_path = run_dir / "checkpoint.md"
    checkpoint_path.write_text(render_checkpoint(charter, plan, source_map), encoding="utf-8")
    return checkpoint_path


def render_source_appendix(source_map: SourceMap) -> str:
    template = load_template("source_appendix.md")
    score_lookup = {score.source_id: score for score in source_map.scores}
    rows: list[str] = []
    for source in source_map.sources:
        score = score_lookup.get(source.id)
        score_text = str(score.final_score) if score is not None else ""
        rows.append(
            "| "
            f"{_table_cell(source.id)} | {_table_cell(source.title)} | "
            f"{_table_cell(source.publisher)} | {_table_cell(source.url)} | "
            f"{_table_cell(source.source_type)} | {_table_cell(source.publication_date)} | "
            f"{score_text} | {_table_cell(source.bias_risk)} | "
            f"{_table_cell(', '.join(source.recommended_uses))} |"
        )
    return render_markdown_template(template, {"rows": "\n".join(rows)})


def render_mock_report(
    *,
    charter: ResearchCharter,
    plan: ResearchPlan,
    source_map: SourceMap,
    evidence_ledger: EvidenceLedger,
) -> Report:
    rendered_template = render_markdown_template(
        load_template(select_report_template_name(charter)),
        {"target": charter.target},
    )
    title = rendered_template.splitlines()[0] if rendered_template.splitlines() else f"# {charter.target}"
    source_ids = sorted(
        {
            claim.source_id
            for claim in evidence_ledger.claims
            if claim.source_id is not None
        }
    )
    key_findings = "\n".join(
        f"- {claim.claim} [{claim.id}]"
        for claim in evidence_ledger.claims[:5]
    ) or "- No evidence claims extracted."
    risks = _bullets(plan.known_risks or source_map.gaps)
    open_questions = _bullets(plan.checkpoint_questions)
    source_appendix = render_source_appendix(source_map)
    if source_appendix.startswith("# "):
        source_appendix = f"#{source_appendix}"

    markdown = (
        f"{title}\n\n"
        "## Executive Summary\n"
        f"- This draft is based on {len(evidence_ledger.claims)} evidence claims "
        f"and {len(source_map.sources)} scored sources.\n\n"
        "## Key Findings\n"
        f"{key_findings}\n\n"
        "## Business Overview\n"
        f"- {charter.target} should be described only from evidence-backed claims.\n\n"
        "## Competitors\n"
        "- Competitive context remains a follow-up item unless supported by extracted evidence.\n\n"
        "## Risks\n"
        f"{risks}\n\n"
        "## Open Questions\n"
        f"{open_questions}\n\n"
        f"{source_appendix}\n"
    )
    return Report(
        title=f"{charter.target} Research Report",
        markdown=markdown,
        source_ids=source_ids,
        claim_ids=[claim.id for claim in evidence_ledger.claims],
        status="draft",
    )


def write_report_artifacts(
    run_dir: Path,
    report: Report,
    *,
    write_final: bool = True,
) -> tuple[Path, Path | None]:
    draft_path = run_dir / "draft_report.md"
    draft_path.write_text(report.markdown, encoding="utf-8")
    final_path = None
    if write_final:
        final_path = run_dir / "report.md"
        final_path.write_text(report.markdown, encoding="utf-8")
    return draft_path, final_path
