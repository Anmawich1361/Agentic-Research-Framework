import pytest

from agentic_research.prompts import load_agent_prompt, load_policy_prompt, load_prompt


def test_load_prompt_by_relative_path() -> None:
    prompt = load_prompt("prompts/agents/intake_agent.md")

    assert "# Intake Agent" in prompt
    assert "structured research charter" in prompt


def test_load_agent_and_policy_prompts_by_name() -> None:
    agent_prompt = load_agent_prompt("intake_agent")
    policy_prompt = load_policy_prompt("source_quality_policy")

    assert "# Intake Agent" in agent_prompt
    assert "# Source Quality Policy" in policy_prompt


def test_missing_prompt_raises_helpful_error() -> None:
    with pytest.raises(FileNotFoundError, match="Prompt not found"):
        load_agent_prompt("does_not_exist")
