from agentic_research.models import ResearchCharter, ResearchPlan
from agentic_research.specialists import runnable_specialist_agent_keys, select_specialists


def _charter(lens: str, target_type: str = "company") -> ResearchCharter:
    return ResearchCharter(
        target="Salesforce",
        target_type=target_type,  # type: ignore[arg-type]
        research_lens=lens,  # type: ignore[arg-type]
        depth="standard",
        deliverable=f"{lens}_brief",
        key_questions=["What matters?"],
    )


def _plan(required_source_types: list[str] | None = None) -> ResearchPlan:
    return ResearchPlan(
        research_questions=["What matters?"],
        report_sections=["overview"],
        required_source_types=required_source_types or ["primary_company"],
        checkpoint_questions=["Which question matters most?"],
    )


def test_select_specialists_for_sales_lens() -> None:
    selected = select_specialists(_charter("sales"), _plan())

    assert selected == ["company", "news", "competitor", "risk_lite"]
    assert runnable_specialist_agent_keys(selected) == ["news", "competitor", "risk"]


def test_select_specialists_for_investment_public_company() -> None:
    selected = select_specialists(_charter("investment"), _plan(["corporate_filing"]))

    assert selected == ["financial", "industry", "competitor", "risk", "filings"]
    assert runnable_specialist_agent_keys(selected) == [
        "financial",
        "industry",
        "competitor",
        "risk",
        "filings",
    ]


def test_select_specialists_for_investment_without_filings_requirement() -> None:
    selected = select_specialists(_charter("investment"), _plan(["primary_company", "news"]))

    assert selected == ["financial", "industry", "competitor", "risk"]


def test_select_specialists_for_industry_and_diligence_lenses() -> None:
    assert select_specialists(_charter("industry", "industry"), _plan()) == [
        "industry",
        "competitor",
        "news",
        "risk",
    ]
    assert select_specialists(_charter("diligence"), _plan(["corporate_filing"])) == [
        "filings",
        "financial",
        "industry",
        "competitor",
        "risk",
        "news",
    ]
