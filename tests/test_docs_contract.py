from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_artifact_contract_documents_expected_run_artifacts() -> None:
    text = _read("docs/ARTIFACT_CONTRACT.md")

    for heading in [
        "Checkpoint Artifacts",
        "Full-Run Artifacts",
        "QA Artifacts",
        "Source Ingestion Artifacts",
        "Review and Diagnostic Artifacts",
        "Publication Contract",
        "Status Contract",
    ]:
        assert f"## {heading}" in text

    for artifact in [
        "metadata.json",
        "charter.json",
        "research_plan.json",
        "sources.json",
        "source_map.json",
        "checkpoint.md",
        "user_feedback.json",
        "source_content.json",
        "source_fetch_log.json",
        "evidence_ledger.json",
        "specialist_analyses.json",
        "draft_report.md",
        "artifact_review.md",
        "run_log.jsonl",
        "qa_review.json",
        "report.md",
        "evidence_review.md",
        "report_revision.md",
        "failure_report.md",
        "error.json",
    ]:
        assert f"`{artifact}`" in text

    assert "RUN_STATUS.md" in text


def test_run_status_documents_status_meaning_artifacts_and_next_actions() -> None:
    text = _read("docs/RUN_STATUS.md")

    for status in [
        "checkpoint_ready",
        "evidence_ready",
        "evidence_needs_review",
        "draft_needs_qa",
        "draft_needs_revision",
        "needs_review",
        "report_ready",
        "failed",
    ]:
        assert f"## `{status}`" in text

    for required_phrase in [
        "Meaning:",
        "Expected artifacts:",
        "`report.md`:",
        "Next action:",
    ]:
        assert required_phrase in text


def test_readme_links_contract_and_current_status_docs() -> None:
    text = _read("README.md")

    for link in [
        "docs/ARTIFACT_CONTRACT.md",
        "docs/RUN_STATUS.md",
        "docs/LOCAL_DEVELOPMENT.md",
        "docs/CURRENT_STATUS.md",
    ]:
        assert f"]({link})" in text
