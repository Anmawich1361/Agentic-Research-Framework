from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias, get_args

from pydantic import BaseModel, TypeAdapter

from agentic_research.models import (
    EvidenceExtractionResult,
    QAReview,
    Report,
    ResearchCharter,
    ResearchPlan,
    SourceCandidate,
    SourceDiscoveryResult,
)
from agentic_research.prompts import load_agent_prompt
from agentic_research.tools.web_search import WebSearchClient, create_web_search_tool


AgentKey: TypeAlias = Literal[
    "intake",
    "planner",
    "source_discovery",
    "evidence_extraction",
    "synthesis",
    "qa",
]


@dataclass(frozen=True)
class AgentSpec:
    key: AgentKey
    name: str
    prompt_name: str
    output_type: type[BaseModel]


@dataclass(frozen=True)
class ResearchAgentSet:
    intake: Any
    planner: Any
    source_discovery: Any
    evidence_extraction: Any
    synthesis: Any
    qa: Any


AGENT_SPECS: dict[AgentKey, AgentSpec] = {
    "intake": AgentSpec("intake", "Intake Agent", "intake_agent", ResearchCharter),
    "planner": AgentSpec("planner", "Research Planner Agent", "planner_agent", ResearchPlan),
    "source_discovery": AgentSpec(
        "source_discovery",
        "Source Discovery Agent",
        "source_discovery_agent",
        SourceDiscoveryResult,
    ),
    "evidence_extraction": AgentSpec(
        "evidence_extraction",
        "Evidence Extraction Agent",
        "evidence_extraction_agent",
        EvidenceExtractionResult,
    ),
    "synthesis": AgentSpec("synthesis", "Synthesis Agent", "synthesis_agent", Report),
    "qa": AgentSpec("qa", "QA Agent", "qa_agent", QAReview),
}


def _validate_agent_key(agent_key: str) -> AgentKey:
    if agent_key not in get_args(AgentKey):
        allowed = ", ".join(get_args(AgentKey))
        raise KeyError(f"Unknown agent key: {agent_key}. Expected one of: {allowed}")
    return agent_key  # type: ignore[return-value]


def get_agent_output_type(agent_key: str) -> type[BaseModel]:
    return AGENT_SPECS[_validate_agent_key(agent_key)].output_type


def create_research_agent(
    agent_key: str,
    *,
    model: str | None = None,
    search_client: WebSearchClient | None = None,
) -> Any:
    """Create an OpenAI Agents SDK agent for one Phase 2 workflow role."""
    from agents import Agent

    spec = AGENT_SPECS[_validate_agent_key(agent_key)]
    tools = []
    if spec.key == "source_discovery":
        tools.append(create_web_search_tool(search_client))

    return Agent(
        name=spec.name,
        instructions=load_agent_prompt(spec.prompt_name),
        model=model,
        output_type=spec.output_type,
        tools=tools,
    )


def create_agent_set(
    *,
    model: str | None = None,
    search_client: WebSearchClient | None = None,
) -> ResearchAgentSet:
    return ResearchAgentSet(
        intake=create_research_agent("intake", model=model),
        planner=create_research_agent("planner", model=model),
        source_discovery=create_research_agent(
            "source_discovery",
            model=model,
            search_client=search_client,
        ),
        evidence_extraction=create_research_agent("evidence_extraction", model=model),
        synthesis=create_research_agent("synthesis", model=model),
        qa=create_research_agent("qa", model=model),
    )


def run_agent_sync(agent: Any, prompt: str) -> Any:
    from agents import Runner

    result = Runner.run_sync(agent, prompt)
    return result.final_output


def coerce_agent_output(output: Any, output_type: type[BaseModel]) -> BaseModel:
    if isinstance(output, output_type):
        return output
    if isinstance(output, str):
        return TypeAdapter(output_type).validate_json(output)
    if isinstance(output, dict):
        return TypeAdapter(output_type).validate_python(output)
    return TypeAdapter(output_type).validate_python(json.loads(json.dumps(output)))


def _extract_target(request: str) -> str:
    cleaned = request.strip()
    cleaned = re.sub(r"^research\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.split(r"\s+before\s+|\s+for\s+|\s+about\s+", cleaned, maxsplit=1)[0]
    return cleaned.strip(" .") or "Unknown target"


def _infer_lens(request: str, explicit_lens: str | None) -> str:
    if explicit_lens:
        return explicit_lens

    lowered = request.lower()
    if "investor" in lowered or "investment" in lowered:
        return "investment"
    if "sales" in lowered or "supplier" in lowered or "vendor" in lowered:
        return "sales"
    if "interview" in lowered:
        return "interview"
    if "diligence" in lowered:
        return "diligence"
    if "strategy" in lowered:
        return "strategy"
    return "general"


def _deliverable_for_lens(lens: str) -> str:
    return {
        "investment": "investment_memo",
        "sales": "meeting_prep_brief",
        "interview": "interview_prep_brief",
        "strategy": "strategy_brief",
        "diligence": "diligence_brief",
    }.get(lens, "company_brief")


def create_mock_charter(
    request: str,
    *,
    mode: str = "standard",
    lens: str | None = None,
) -> ResearchCharter:
    target = _extract_target(request).title()
    inferred_lens = _infer_lens(request, lens)

    return ResearchCharter(
        target=target,
        target_type="company",
        research_lens=inferred_lens,  # type: ignore[arg-type]
        depth=mode,  # type: ignore[arg-type]
        deliverable=_deliverable_for_lens(inferred_lens),
        geography="global",
        time_horizon="current position and recent developments",
        key_questions=[
            f"What does {target} do and where does it compete?",
            f"What matters most for the {inferred_lens} research lens?",
            "Which sources should be reviewed before deeper research?",
            "What risks, gaps, or open questions should guide follow-up?",
        ],
        assumptions=[
            "Phase 1 uses deterministic mock outputs only.",
            "The request is treated as company research unless later context says otherwise.",
        ],
        missing_context=[
            "User has not approved deep research yet.",
            "No live source discovery has been performed in Phase 1.",
        ],
    )


def create_mock_plan(charter: ResearchCharter) -> ResearchPlan:
    return ResearchPlan(
        research_questions=charter.key_questions,
        report_sections=[
            "executive_summary",
            "company_overview",
            "market_context",
            "source_map",
            "risks",
            "open_questions",
        ],
        required_source_types=[
            "corporate_filing",
            "primary_company",
            "earnings_transcript",
            "news",
            "industry_primer",
        ],
        likely_specialists=["industry", "financial", "news", "risk"],
        checkpoint_questions=[
            "Is the inferred target correct?",
            "Should the research lens be narrowed before deep research?",
            "Are there specific competitors, geographies, or time periods to prioritize?",
        ],
        known_risks=[
            "Mock source candidates are placeholders and must be replaced by live discovery later.",
            "No evidence ledger has been populated for report claims yet.",
        ],
        data_gaps=[
            "Live source discovery is deferred to Phase 2 and Phase 3.",
            "User approval is required before deeper research.",
        ],
    )


def discover_mock_sources(charter: ResearchCharter) -> list[SourceCandidate]:
    target = charter.target
    target_slug = re.sub(r"[^a-z0-9]+", "-", target.lower()).strip("-") or "target"

    return [
        SourceCandidate(
            id=f"src_{target_slug}_filing",
            title=f"Mock {target} annual filing",
            publisher="Mock regulatory source",
            url=f"https://example.com/{target_slug}/annual-filing",
            source_type="corporate_filing",
            publication_date="2026-03-01",
            relevance_rationale="High-authority starting point for company and risk research.",
            recommended_uses=["business overview", "risk factors", "financial profile"],
            bias_risk="low",
            notes="Placeholder source for deterministic Phase 1 scoring.",
        ),
        SourceCandidate(
            id=f"src_{target_slug}_company",
            title=f"Mock {target} company overview",
            publisher=target,
            url=f"https://example.com/{target_slug}/company-overview",
            source_type="primary_company",
            publication_date="2026-02-15",
            relevance_rationale="Primary source for positioning, products, and company language.",
            recommended_uses=["products", "positioning"],
            bias_risk="high",
            notes="Placeholder source for deterministic Phase 1 scoring.",
        ),
        SourceCandidate(
            id=f"src_{target_slug}_transcript",
            title=f"Mock {target} earnings transcript",
            publisher="Mock transcript provider",
            url=f"https://example.com/{target_slug}/earnings-transcript",
            source_type="earnings_transcript",
            publication_date="2026-01-25",
            relevance_rationale="Useful for management commentary and recent priorities.",
            recommended_uses=["management commentary", "recent developments"],
            bias_risk="medium",
            notes="Placeholder source for deterministic Phase 1 scoring.",
        ),
        SourceCandidate(
            id=f"src_{target_slug}_industry",
            title=f"Mock industry primer relevant to {target}",
            publisher="Mock industry source",
            url=f"https://example.com/{target_slug}/industry-primer",
            source_type="industry_primer",
            publication_date="2025-10-01",
            relevance_rationale="Useful for market structure and competitive context.",
            recommended_uses=["industry context", "competitors"],
            bias_risk="medium",
            notes="Placeholder source for deterministic Phase 1 scoring.",
        ),
        SourceCandidate(
            id=f"src_{target_slug}_news",
            title=f"Mock recent news coverage for {target}",
            publisher="Mock news source",
            url=f"https://example.com/{target_slug}/recent-news",
            source_type="news",
            publication_date="2026-04-15",
            relevance_rationale="Useful for recent developments and issues to verify.",
            recommended_uses=["recent developments", "open questions"],
            bias_risk="medium",
            notes="Placeholder source for deterministic Phase 1 scoring.",
        ),
    ]
