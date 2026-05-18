from __future__ import annotations

from agentic_research.models import ResearchCharter, ResearchPlan, SourceMap, SpecialistAnalysis


SPECIALIST_AGENT_KEYS = {"industry", "competitor", "news", "risk", "financial", "filings"}
SPECIALIST_AGENT_BY_SELECTION = {
    "industry": "industry",
    "competitor": "competitor",
    "news": "news",
    "risk": "risk",
    "risk_lite": "risk",
    "financial": "financial",
    "filings": "filings",
}


def _include_filings(charter: ResearchCharter, plan: ResearchPlan) -> bool:
    return charter.target_type in {"company", "competitor_set"} and any(
        source_type in {"corporate_filing", "filings", "filing", "investor_material"}
        for source_type in plan.required_source_types
    )


def select_specialists(charter: ResearchCharter, plan: ResearchPlan) -> list[str]:
    if charter.research_lens == "sales":
        return ["company", "news", "competitor", "risk_lite"]
    if charter.research_lens == "investment":
        selected = ["financial", "industry", "competitor", "risk"]
        if _include_filings(charter, plan):
            selected.append("filings")
        return selected
    if charter.research_lens == "interview":
        return ["company", "history", "news", "strategy"]
    if charter.research_lens == "industry":
        return ["industry", "competitor", "news", "risk"]
    if charter.research_lens == "diligence":
        return ["filings", "financial", "industry", "competitor", "risk", "news"]
    return plan.likely_specialists or ["industry", "news", "risk"]


def runnable_specialist_agent_keys(selected_specialists: list[str]) -> list[str]:
    runnable: list[str] = []
    for specialist in selected_specialists:
        agent_key = SPECIALIST_AGENT_BY_SELECTION.get(specialist)
        if agent_key is None or agent_key not in SPECIALIST_AGENT_KEYS:
            continue
        if agent_key not in runnable:
            runnable.append(agent_key)
    return runnable


def build_mock_specialist_analyses(
    selected_specialists: list[str],
    source_map: SourceMap,
) -> list[SpecialistAnalysis]:
    source_ids = [source.id for source in source_map.sources[:1]]
    return [
        SpecialistAnalysis(
            specialist=specialist,
            summary=f"Mock {specialist} analysis is deferred to live specialist agents.",
            source_ids=source_ids,
        )
        for specialist in selected_specialists
    ]
