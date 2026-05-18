from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agentic_research.models import ResearchCharter, ResearchPlan, SourceMap
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
