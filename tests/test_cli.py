import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from agentic_research import cli
from agentic_research.models import QAReview, ResearchCharter, ResearchPlan, RunMetadata, SourceMap
from agentic_research.orchestrator import run_research


def test_pyproject_declares_src_layout_for_editable_install() -> None:
    project_root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))

    assert config["build-system"]["build-backend"] == "setuptools.build_meta"
    assert "setuptools>=69" in config["build-system"]["requires"]
    assert "wheel" in config["build-system"]["requires"]
    assert config["tool"]["setuptools"]["package-dir"] == {"": "src"}
    assert config["tool"]["setuptools"]["packages"]["find"]["where"] == ["src"]
    assert config["tool"]["setuptools"]["packages"]["find"]["include"] == [
        "agentic_research*"
    ]


def test_console_script_entrypoint_is_installed_for_editable_environment() -> None:
    arf_script = Path(sys.executable).with_name("arf")

    assert arf_script.exists()

    result = subprocess.run(
        [str(arf_script), "--help"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0
    assert "Agentic Research Framework CLI" in result.stdout


def test_cli_run_subcommand_invokes_mock_checkpoint(tmp_path, monkeypatch) -> None:
    def run_in_tmp_dir(*args, **kwargs):
        kwargs["runs_dir"] = tmp_path / "runs"
        return run_research(*args, **kwargs)

    monkeypatch.setattr(cli, "run_research", run_in_tmp_dir)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["run", "Research Nvidia before an investor meeting", "--mock", "--checkpoint-only"],
    )

    assert result.exit_code == 0
    assert "run_id:" in result.stdout
    assert "checkpoint:" in result.stdout
    assert any((tmp_path / "runs").iterdir())


def test_cli_run_subcommand_accepts_live_checkpoint_without_mock(monkeypatch, tmp_path) -> None:
    captured = {}
    checkpoint_path = tmp_path / "runs" / "run_live" / "checkpoint.md"
    checkpoint_path.parent.mkdir(parents=True)
    checkpoint_path.write_text("# checkpoint")

    result_obj = SimpleNamespace(
        metadata=RunMetadata(
            run_id="run_live",
            created_at="2026-05-18T00:00:00+00:00",
            request="Research Costco before a supplier meeting",
            status="checkpoint_ready",
            mode="standard",
            lens="sales",
            mock=False,
        ),
        checkpoint_path=checkpoint_path,
        run_dir=checkpoint_path.parent,
        charter=ResearchCharter(
            target="Costco",
            target_type="company",
            research_lens="sales",
            depth="standard",
            deliverable="meeting_prep_brief",
            key_questions=["What matters for the supplier meeting?"],
        ),
        research_plan=ResearchPlan(
            research_questions=["What matters for the supplier meeting?"],
            report_sections=["overview"],
            required_source_types=["primary_company"],
            checkpoint_questions=["Which category?"],
        ),
        sources=[],
        source_map=SourceMap(sources=[], scores=[], gaps=[]),
    )

    def fake_run_research(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return result_obj

    monkeypatch.setattr(cli, "run_research", fake_run_research)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["run", "Research Costco before a supplier meeting", "--checkpoint-only"],
    )

    assert result.exit_code == 0
    assert captured["args"] == ("Research Costco before a supplier meeting",)
    assert captured["kwargs"]["mock"] is False
    assert captured["kwargs"]["checkpoint_only"] is True
    assert "run_live" in result.stdout


def test_cli_run_subcommand_accepts_full_mode(monkeypatch, tmp_path) -> None:
    captured = {}
    checkpoint_path = tmp_path / "runs" / "run_full" / "checkpoint.md"
    checkpoint_path.parent.mkdir(parents=True)
    checkpoint_path.write_text("# checkpoint")

    result_obj = SimpleNamespace(
        metadata=RunMetadata(
            run_id="run_full",
            created_at="2026-05-18T00:00:00+00:00",
            request="Research ServiceTitan before a sales meeting",
            status="evidence_ready",
            mode="standard",
            lens="sales",
            mock=False,
        ),
        checkpoint_path=checkpoint_path,
        run_dir=checkpoint_path.parent,
        charter=ResearchCharter(
            target="ServiceTitan",
            target_type="company",
            research_lens="sales",
            depth="standard",
            deliverable="meeting_prep_brief",
            key_questions=["What matters for the sales meeting?"],
        ),
        research_plan=ResearchPlan(
            research_questions=["What matters for the sales meeting?"],
            report_sections=["overview"],
            required_source_types=["primary_company"],
            checkpoint_questions=["Which persona?"],
        ),
        sources=[],
        source_map=SourceMap(sources=[], scores=[], gaps=[]),
        evidence_ledger=None,
    )

    def fake_run_research(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return result_obj

    monkeypatch.setattr(cli, "run_research", fake_run_research)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["run", "Research ServiceTitan before a sales meeting", "--full"],
    )

    assert result.exit_code == 0
    assert captured["kwargs"]["full"] is True
    assert captured["kwargs"]["checkpoint_only"] is False
    assert "run_full" in result.stdout


def test_cli_run_subcommand_accepts_qa_mode(monkeypatch, tmp_path) -> None:
    captured = {}
    checkpoint_path = tmp_path / "runs" / "run_qa" / "checkpoint.md"
    checkpoint_path.parent.mkdir(parents=True)
    checkpoint_path.write_text("# checkpoint")

    result_obj = SimpleNamespace(
        metadata=RunMetadata(
            run_id="run_qa",
            created_at="2026-05-18T00:00:00+00:00",
            request="Research Salesforce for an investment memo",
            status="report_ready",
            mode="standard",
            lens="investment",
            mock=False,
        ),
        checkpoint_path=checkpoint_path,
        run_dir=checkpoint_path.parent,
        charter=ResearchCharter(
            target="Salesforce",
            target_type="company",
            research_lens="investment",
            depth="standard",
            deliverable="investment_memo",
            key_questions=["What matters for the investment memo?"],
        ),
        research_plan=ResearchPlan(
            research_questions=["What matters for the investment memo?"],
            report_sections=["overview"],
            required_source_types=["primary_company"],
            checkpoint_questions=["Which risk matters?"],
        ),
        sources=[],
        source_map=SourceMap(sources=[], scores=[], gaps=[]),
        evidence_ledger=None,
        qa_review=QAReview(ready_to_publish=True, issues=[]),
    )

    def fake_run_research(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return result_obj

    monkeypatch.setattr(cli, "run_research", fake_run_research)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["run", "Research Salesforce for an investment memo", "--full", "--qa"],
    )

    assert result.exit_code == 0
    assert captured["kwargs"]["full"] is True
    assert captured["kwargs"]["qa"] is True
    assert "run_qa" in result.stdout


def test_cli_review_run_command_writes_artifact_review(tmp_path) -> None:
    run_dir = tmp_path / "run_cli_review"
    run_dir.mkdir()
    (run_dir / "metadata.json").write_text(
        '{"run_id":"run_cli_review","created_at":"2026-05-18T00:00:00+00:00",'
        '"request":"Research Costco","status":"draft_needs_qa","mock":false}',
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(cli.app, ["review-run", str(run_dir)])

    assert result.exit_code == 0
    assert "artifact_review:" in result.stdout
    assert "status: draft_needs_qa" in result.stdout
    assert "final_report_published: no" in result.stdout
    assert "qa_issues: high=0 medium=0 low=0" in result.stdout
    assert "source_fetches:" in result.stdout
    assert "next_action:" in result.stdout
    assert (run_dir / "artifact_review.md").exists()


def test_cli_runs_and_show_commands_list_checkpoint_artifacts(tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "run_cli_show"
    run_dir.mkdir()
    (run_dir / "metadata.json").write_text(
        '{"run_id":"run_cli_show","created_at":"2026-05-18T00:00:00+00:00",'
        '"request":"Research Costco","status":"checkpoint_ready","lens":"sales",'
        '"mock":true}',
        encoding="utf-8",
    )
    (run_dir / "checkpoint.md").write_text("# checkpoint", encoding="utf-8")
    monkeypatch.setattr(cli, "get_artifact_dir", lambda: tmp_path)
    runner = CliRunner()

    runs_result = runner.invoke(cli.app, ["runs"])
    show_result = runner.invoke(cli.app, ["show", "run_cli_show"])

    assert runs_result.exit_code == 0
    assert "run_cli_show" in runs_result.stdout
    assert "checkpoint_ready" in runs_result.stdout
    assert show_result.exit_code == 0
    assert "checkpoint.md: present" in show_result.stdout
    assert "user_feedback.json: missing" in show_result.stdout


def test_cli_add_feedback_command_writes_user_feedback(tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "run_cli_feedback"
    run_dir.mkdir()
    monkeypatch.setattr(cli, "get_artifact_dir", lambda: tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "add-feedback",
            "run_cli_feedback",
            "--answer",
            "Which category?=Frozen food",
            "--approve-source",
            "src_keep",
            "--reject-source",
            "src_bad",
            "--depth-override",
            "brief",
            "--lens-override",
            "sales",
            "--note",
            "Focus on supplier readiness.",
            "--priority-topic",
            "cold-chain reliability",
        ],
    )

    assert result.exit_code == 0
    feedback = (run_dir / "user_feedback.json").read_text(encoding="utf-8")
    assert "Frozen food" in feedback
    assert "src_keep" in feedback
    assert "src_bad" in feedback
    assert "cold-chain reliability" in feedback


def test_cli_continue_command_invokes_continue_research(monkeypatch, tmp_path) -> None:
    captured = {}
    checkpoint_path = tmp_path / "runs" / "run_continue" / "checkpoint.md"
    checkpoint_path.parent.mkdir(parents=True)
    checkpoint_path.write_text("# checkpoint", encoding="utf-8")
    result_obj = SimpleNamespace(
        metadata=RunMetadata(
            run_id="run_continue",
            created_at="2026-05-18T00:00:00+00:00",
            request="Research Costco",
            status="draft_needs_qa",
            mode="brief",
            lens="sales",
            mock=True,
        ),
        checkpoint_path=checkpoint_path,
        draft_report_path=checkpoint_path.parent / "draft_report.md",
        report_path=None,
        report=object(),
    )

    def fake_continue_research(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return result_obj

    monkeypatch.setattr(cli, "continue_research", fake_continue_research)
    runner = CliRunner()

    result = runner.invoke(cli.app, ["continue", "run_continue", "--qa", "--mock"])

    assert result.exit_code == 0
    assert captured["args"] == ("run_continue",)
    assert captured["kwargs"]["qa"] is True
    assert captured["kwargs"]["mock"] is True
    assert "status: draft_needs_qa" in result.stdout
