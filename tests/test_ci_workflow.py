from pathlib import Path

import yaml


def test_ci_workflow_runs_setup_and_check_without_live_api_calls() -> None:
    workflow_path = Path(".github/workflows/ci.yml")

    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["check"]["steps"]
    run_commands = "\n".join(step.get("run", "") for step in steps)

    assert workflow["name"] == "CI"
    assert "make setup" in run_commands
    assert "make check" in run_commands
    assert "smoke-live" not in run_commands
    assert "OPENAI_API_KEY" not in run_commands
