import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from agentic_research import cli
from agentic_research.models import (
    QAReview,
    ResearchCharter,
    ResearchPlan,
    RunMetadata,
    SourceCandidate,
    SourceMap,
    SourceScore,
)
from agentic_research.orchestrator import run_research
from agentic_research.report_writer import write_json_artifact


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


def _write_wizard_checkpoint_artifacts(
    run_dir: Path,
    *,
    checkpoint_questions: list[str] | None = None,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "checkpoint.md").write_text("# checkpoint", encoding="utf-8")
    plan = ResearchPlan(
        research_questions=["What matters for the meeting?"],
        report_sections=["overview"],
        required_source_types=["primary_company"],
        checkpoint_questions=checkpoint_questions
        if checkpoint_questions is not None
        else ["Which metric matters most?", "What should be excluded?"],
    )
    source_map = SourceMap(
        sources=[
            SourceCandidate(
                id="src1",
                title="Annual report",
                publisher="Company",
                url="https://example.com/annual-report",
                source_type="primary_company",
                bias_risk="low",
                relevance_rationale="Primary filing source.",
                recommended_uses=["business overview"],
            ),
            SourceCandidate(
                id="src2",
                title="Industry article",
                publisher="Trade Press",
                url="https://example.com/industry",
                source_type="industry",
                bias_risk="medium",
                relevance_rationale="Useful sector context.",
                recommended_uses=["market context"],
            ),
        ],
        scores=[
            SourceScore(
                source_id="src1",
                authority_score=5,
                relevance_score=5,
                recency_score=4,
                coverage_score=5,
                bias_risk="low",
                final_score=4.8,
                include=True,
            ),
            SourceScore(
                source_id="src2",
                authority_score=3,
                relevance_score=4,
                recency_score=3,
                coverage_score=3,
                bias_risk="medium",
                final_score=3.4,
                include=False,
            ),
        ],
        gaps=[],
    )
    write_json_artifact(run_dir / "research_plan.json", plan)
    write_json_artifact(run_dir / "source_map.json", source_map)


def _wizard_result(
    run_dir: Path,
    *,
    run_id: str,
    request: str,
    status: str,
    mock: bool,
    lens: str = "investment",
    mode: str = "standard",
    report_ready: bool = False,
    draft_report: bool = False,
) -> SimpleNamespace:
    checkpoint_path = run_dir / "checkpoint.md"
    report_path = run_dir / "report.md" if report_ready else None
    if report_path is not None:
        report_path.write_text("# report", encoding="utf-8")
    draft_report_path = run_dir / "draft_report.md" if draft_report else None
    if draft_report_path is not None:
        draft_report_path.write_text("# draft", encoding="utf-8")
    return SimpleNamespace(
        metadata=RunMetadata(
            run_id=run_id,
            created_at="2026-05-18T00:00:00+00:00",
            request=request,
            status=status,
            mode=mode,
            lens=lens,
            mock=mock,
        ),
        checkpoint_path=checkpoint_path,
        run_dir=run_dir,
        draft_report_path=draft_report_path,
        report_path=report_path,
        report=object() if report_ready or draft_report else None,
    )


def test_cli_wizard_loads_repo_dotenv_before_run(monkeypatch, tmp_path) -> None:
    calls = []
    run_dir = tmp_path / "runs" / "run_wizard_dotenv"
    _write_wizard_checkpoint_artifacts(run_dir, checkpoint_questions=[])
    result_obj = _wizard_result(
        run_dir,
        run_id="run_wizard_dotenv",
        request="Research ATS Corporation before meeting",
        status="checkpoint_ready",
        mock=False,
    )

    def fake_load_dotenv(path, *, override=False):
        calls.append((Path(path), override))
        return True

    def fake_run_research(*args, **kwargs):
        assert calls
        return result_obj

    def fake_continue_research(*args, **kwargs):
        return _wizard_result(
            run_dir,
            run_id="run_wizard_dotenv",
            request="Research ATS Corporation before meeting",
            status="report_ready",
            mock=False,
            report_ready=True,
        )

    monkeypatch.setattr(cli, "load_dotenv", fake_load_dotenv, raising=False)
    monkeypatch.setattr(cli, "run_research", fake_run_research)
    monkeypatch.setattr(cli, "continue_research", fake_continue_research)
    monkeypatch.setattr(cli, "_open_report_path", lambda path: True)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["wizard"],
        input="ATS Corporation\nmeeting\ninvestment\nstandard\n\n\n\n",
    )

    assert result.exit_code == 0
    assert calls == [(Path(cli.__file__).resolve().parents[2] / ".env", False)]


def test_cli_wizard_guided_default_answers_checkpoint_and_opens_report(
    monkeypatch,
    tmp_path,
) -> None:
    captured = {"run": None, "continue": None, "opened": []}
    run_dir = tmp_path / "runs" / "run_wizard_guided"
    _write_wizard_checkpoint_artifacts(run_dir)
    checkpoint_result = _wizard_result(
        run_dir,
        run_id="run_wizard_guided",
        request="Research Nvidia before an investor meeting",
        status="checkpoint_ready",
        mock=True,
    )

    def fake_run_research(*args, **kwargs):
        captured["run"] = (args, kwargs)
        return checkpoint_result

    def fake_continue_research(*args, **kwargs):
        captured["continue"] = (args, kwargs)
        return _wizard_result(
            run_dir,
            run_id="run_wizard_guided",
            request="Research Nvidia before an investor meeting",
            status="report_ready",
            mock=True,
            report_ready=True,
        )

    monkeypatch.setattr(cli, "run_research", fake_run_research)
    monkeypatch.setattr(cli, "continue_research", fake_continue_research)
    monkeypatch.setattr(
        cli,
        "_open_report_path",
        lambda path: captured["opened"].append(path) or True,
    )
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["wizard", "--mock", "--model", "gpt-test"],
        input=(
            "Nvidia\n"
            "an investor meeting\n"
            "1\n"
            "2\n"
            "\n"
            "Cash conversion\n"
            "Unsupported valuation claims\n"
            "\n"
            "Focus on filings.\n"
        ),
    )

    assert result.exit_code == 0
    run_args, run_kwargs = captured["run"]
    assert run_args == ("Research Nvidia before an investor meeting",)
    assert run_kwargs["checkpoint_only"] is True
    assert run_kwargs["full"] is False
    assert run_kwargs["qa"] is False
    assert run_kwargs["mock"] is True
    assert run_kwargs["model"] == "gpt-test"
    assert run_kwargs["lens"] == "investment"
    assert run_kwargs["mode"] == "standard"
    continue_args, continue_kwargs = captured["continue"]
    assert continue_args == (run_dir,)
    assert continue_kwargs["qa"] is True
    assert continue_kwargs["mock"] is True
    assert continue_kwargs["model"] == "gpt-test"
    feedback = cli.load_user_feedback(run_dir)
    assert [answer.answer for answer in feedback.answered_checkpoint_questions] == [
        "Cash conversion",
        "Unsupported valuation claims",
    ]
    assert feedback.approved_source_ids == ["src1"]
    assert feedback.user_notes == "Focus on filings."
    assert captured["opened"] == [run_dir / "report.md"]
    assert "run_id: run_wizard_guided" in result.stdout
    assert "status: report_ready" in result.stdout
    assert "checkpoint:" in result.stdout
    assert "user_feedback:" in result.stdout
    assert "report:" in result.stdout
    assert "opened_report:" in result.stdout
    assert "next_show: .venv/bin/arf show run_wizard_guided" in result.stdout
    assert "next_review: .venv/bin/arf review-run run_wizard_guided" in result.stdout


def test_cli_wizard_no_open_suppresses_report_opener(monkeypatch, tmp_path) -> None:
    captured = {"opened": []}
    run_dir = tmp_path / "runs" / "run_wizard_no_open"
    _write_wizard_checkpoint_artifacts(run_dir, checkpoint_questions=[])
    checkpoint_result = _wizard_result(
        run_dir,
        run_id="run_wizard_no_open",
        request="Research Nvidia before an investor meeting",
        status="checkpoint_ready",
        mock=True,
    )

    monkeypatch.setattr(cli, "run_research", lambda *args, **kwargs: checkpoint_result)
    monkeypatch.setattr(
        cli,
        "continue_research",
        lambda *args, **kwargs: _wizard_result(
            run_dir,
            run_id="run_wizard_no_open",
            request="Research Nvidia before an investor meeting",
            status="report_ready",
            mock=True,
            report_ready=True,
        ),
    )
    monkeypatch.setattr(
        cli,
        "_open_report_path",
        lambda path: captured["opened"].append(path) or True,
    )
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["wizard", "--mock", "--no-open"],
        input="Nvidia\nan investor meeting\n1\n2\n\n\n\n",
    )

    assert result.exit_code == 0
    assert captured["opened"] == []
    assert "opened_report:" not in result.stdout


def test_cli_wizard_needs_review_does_not_open_draft(monkeypatch, tmp_path) -> None:
    captured = {"opened": []}
    run_dir = tmp_path / "runs" / "run_wizard_needs_review"
    _write_wizard_checkpoint_artifacts(run_dir, checkpoint_questions=[])
    checkpoint_result = _wizard_result(
        run_dir,
        run_id="run_wizard_needs_review",
        request="Research Nvidia before an investor meeting",
        status="checkpoint_ready",
        mock=True,
    )

    monkeypatch.setattr(cli, "run_research", lambda *args, **kwargs: checkpoint_result)
    monkeypatch.setattr(
        cli,
        "continue_research",
        lambda *args, **kwargs: _wizard_result(
            run_dir,
            run_id="run_wizard_needs_review",
            request="Research Nvidia before an investor meeting",
            status="needs_review",
            mock=True,
            draft_report=True,
        ),
    )
    monkeypatch.setattr(
        cli,
        "_open_report_path",
        lambda path: captured["opened"].append(path) or True,
    )
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["wizard", "--mock"],
        input="Nvidia\nan investor meeting\n1\n2\n\n\n\n",
    )

    assert result.exit_code == 0
    assert captured["opened"] == []
    assert "status: needs_review" in result.stdout
    assert "draft_report:" in result.stdout
    assert "\nreport:" not in result.stdout
    assert "next_continue: .venv/bin/arf continue run_wizard_needs_review --qa" in result.stdout


def test_cli_wizard_checkpoint_only_preserves_manual_path(monkeypatch, tmp_path) -> None:
    captured = {"run": None}
    run_dir = tmp_path / "runs" / "run_wizard_checkpoint_only"
    run_dir.mkdir(parents=True)
    (run_dir / "checkpoint.md").write_text("# checkpoint", encoding="utf-8")
    checkpoint_result = _wizard_result(
        run_dir,
        run_id="run_wizard_checkpoint_only",
        request="Research Nvidia before an investor meeting",
        status="checkpoint_ready",
        mock=True,
    )

    def fake_run_research(*args, **kwargs):
        captured["run"] = (args, kwargs)
        return checkpoint_result

    monkeypatch.setattr(cli, "run_research", fake_run_research)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["wizard", "--mock", "--model", "gpt-test"],
        input="Nvidia\nan investor meeting\n1\n2\n2\n",
    )

    assert result.exit_code == 0
    run_args, run_kwargs = captured["run"]
    assert run_args == ("Research Nvidia before an investor meeting",)
    assert run_kwargs["checkpoint_only"] is True
    assert run_kwargs["full"] is False
    assert run_kwargs["qa"] is False
    assert run_kwargs["mock"] is True
    assert run_kwargs["model"] == "gpt-test"
    assert run_kwargs["lens"] == "investment"
    assert run_kwargs["mode"] == "standard"
    assert "run_id: run_wizard_checkpoint_only" in result.stdout
    assert "status: checkpoint_ready" in result.stdout
    assert "next_approve: .venv/bin/arf approve-sources run_wizard_checkpoint_only" in result.stdout
    assert "next_continue: .venv/bin/arf continue run_wizard_checkpoint_only --qa" in result.stdout


def test_cli_wizard_can_run_full_qa_with_custom_request(monkeypatch, tmp_path) -> None:
    captured = {}
    checkpoint_path = tmp_path / "runs" / "run_wizard_full" / "checkpoint.md"
    checkpoint_path.parent.mkdir(parents=True)
    checkpoint_path.write_text("# checkpoint", encoding="utf-8")
    report_path = checkpoint_path.parent / "report.md"
    result_obj = SimpleNamespace(
        metadata=RunMetadata(
            run_id="run_wizard_full",
            created_at="2026-05-18T00:00:00+00:00",
            request="Research Costco before a supplier meeting",
            status="report_ready",
            mode="brief",
            lens="sales",
            mock=False,
        ),
        checkpoint_path=checkpoint_path,
        run_dir=checkpoint_path.parent,
        draft_report_path=checkpoint_path.parent / "draft_report.md",
        report_path=report_path,
        report=object(),
    )

    def fake_run_research(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return result_obj

    monkeypatch.setattr(cli, "run_research", fake_run_research)
    monkeypatch.setattr(cli, "_open_report_path", lambda path: True)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["wizard"],
        input="Research Costco before a supplier meeting\n2\n1\n3\n",
    )

    assert result.exit_code == 0
    assert captured["args"] == ("Research Costco before a supplier meeting",)
    assert captured["kwargs"]["checkpoint_only"] is False
    assert captured["kwargs"]["full"] is True
    assert captured["kwargs"]["qa"] is True
    assert captured["kwargs"]["mock"] is False
    assert captured["kwargs"]["model"] is None
    assert captured["kwargs"]["lens"] == "sales"
    assert captured["kwargs"]["mode"] == "brief"
    assert "run_id: run_wizard_full" in result.stdout
    assert "status: report_ready" in result.stdout
    assert "report:" in result.stdout
    assert "opened_report:" in result.stdout
    assert "next_show: .venv/bin/arf show run_wizard_full" in result.stdout
    assert "next_review: .venv/bin/arf review-run run_wizard_full" in result.stdout
    assert "next_approve:" not in result.stdout


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
