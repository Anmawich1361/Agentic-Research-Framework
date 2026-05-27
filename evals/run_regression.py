#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import agentic_research.orchestrator as orchestrator  # noqa: E402
from agentic_research.evidence_pipeline import (  # noqa: E402
    DIRECT_EVIDENCE_SUFFICIENCY_WARNING,
)
from agentic_research.models import (  # noqa: E402
    EvidenceClaim,
    EvidenceExtractionResult,
    QAReview,
    Report,
    ResearchCharter,
    ResearchPlan,
    SourceCandidate,
    SourceDiscoveryResult,
    SpecialistAnalysis,
    UserFeedback,
)
from agentic_research.source_ingestion import SourceHttpResponse  # noqa: E402
from agentic_research.tools.web_search import SearchResult, WebSearchClient  # noqa: E402


@dataclass(frozen=True)
class RegressionCheck:
    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class RegressionResult:
    scenario_id: str
    name: str
    metadata_status: str
    run_dir: Path
    checks: list[RegressionCheck]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def to_dict(self) -> dict[str, Any]:
        failed_checks = [check for check in self.checks if not check.passed]
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "metadata_status": self.metadata_status,
            "run_dir": str(self.run_dir),
            "passed": self.passed,
            "checks": [check.to_dict() for check in self.checks],
            "failed_checks": [check.to_dict() for check in failed_checks],
            "failure_reasons": [
                f"{check.name}: {check.detail}" for check in failed_checks
            ],
        }


class _AnyQuerySearchProvider:
    def __init__(self, results: Sequence[SearchResult]) -> None:
        self.results = list(results)

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        return self.results[:max_results]


def _dummy_agent_set(**kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(
        intake=object(),
        planner=object(),
        source_discovery=object(),
        evidence_extraction=object(),
        synthesis=object(),
        qa=object(),
        industry=object(),
        competitor=object(),
        news=object(),
        risk=object(),
        financial=object(),
        filings=object(),
    )


@contextmanager
def _patched_agent_set() -> Any:
    original = orchestrator.create_agent_set
    orchestrator.create_agent_set = _dummy_agent_set
    try:
        yield
    finally:
        orchestrator.create_agent_set = original


def _json_payload_from_prompt(prompt: str) -> dict[str, Any]:
    payload = prompt.split("```json\n", 1)[1].split("\n```", 1)[0]
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise TypeError("Expected JSON object prompt payload.")
    return parsed


def _charter() -> ResearchCharter:
    return ResearchCharter(
        target="Costco",
        target_type="company",
        research_lens="sales",
        depth="brief",
        deliverable="meeting_prep_brief",
        key_questions=["What matters before the supplier meeting?"],
    )


def _plan(required_source_types: list[str] | None = None) -> ResearchPlan:
    return ResearchPlan(
        research_questions=["What should suppliers understand about Costco?"],
        report_sections=["overview", "supplier_context"],
        required_source_types=required_source_types or [
            "primary_company",
            "corporate_filing",
        ],
        checkpoint_questions=["Which supplier category should be prioritized?"],
        likely_specialists=["news", "risk"],
        known_risks=["Supplier category is not identified."],
        data_gaps=["Buyer team and region are not identified."],
    )


def _direct_sources() -> list[SourceCandidate]:
    return [
        SourceCandidate(
            id="src_vendor",
            title="Costco vendor information",
            publisher="Costco Wholesale",
            url="https://example.com/costco-vendor",
            source_type="primary_company",
            relevance_rationale="Primary source for vendor routing.",
            recommended_uses=["supplier meeting"],
            bias_risk="medium",
            publication_date="2026-01-15",
        ),
        SourceCandidate(
            id="src_10k",
            title="Costco annual report",
            publisher="SEC",
            url="https://example.com/costco-10k",
            source_type="corporate_filing",
            relevance_rationale="Primary filing for business context.",
            recommended_uses=["business context", "risk context"],
            bias_risk="low",
            publication_date="2025-10-08",
        ),
    ]


def _direct_claims() -> list[EvidenceClaim]:
    return [
        EvidenceClaim(
            id="claim_vendor",
            claim="Costco publishes vendor contact paths for prospective suppliers.",
            claim_type="fact",
            source_id="src_vendor",
            source_title="Costco vendor information",
            source_url="https://example.com/costco-vendor",
            source_type="primary_company",
            confidence="high",
            report_section="What We Know",
            quote_or_excerpt="Vendor inquiries may be directed to the applicable buying office.",
        ),
        EvidenceClaim(
            id="claim_model",
            claim="Costco describes its warehouse model as focused on member value.",
            claim_type="fact",
            source_id="src_10k",
            source_title="Costco annual report",
            source_url="https://example.com/costco-10k",
            source_type="corporate_filing",
            confidence="high",
            report_section="Context for Meeting",
            quote_or_excerpt="We operate membership warehouses based on value.",
        ),
        EvidenceClaim(
            id="claim_supply",
            claim="Costco identifies merchandise availability as an operating risk.",
            claim_type="fact",
            source_id="src_10k",
            source_title="Costco annual report",
            source_url="https://example.com/costco-10k",
            source_type="corporate_filing",
            confidence="high",
            report_section="Risks and Watchouts",
            quote_or_excerpt="Supply disruptions may affect merchandise availability.",
        ),
    ]


def _report(
    *,
    title: str = "Costco Supplier Meeting Prep",
    stale_claim: bool = False,
) -> Report:
    context_claim = "claim_stale" if stale_claim else "claim_model"
    claim_ids = ["claim_vendor", "claim_model", "claim_supply"]
    if stale_claim:
        claim_ids.append("claim_stale")
    return Report(
        title=title,
        source_ids=["src_vendor", "src_10k"],
        claim_ids=claim_ids,
        markdown=(
            f"# {title}\n\n"
            "## Executive Summary\n"
            "Costco supplier prep can use vendor routing, member-value positioning, "
            "and merchandise-availability risk. [claim_vendor] [claim_model] [claim_supply]\n\n"
            "## Context for Meeting\n"
            f"Costco's warehouse model emphasizes member value. [{context_claim}]\n\n"
            "## What We Know\n"
            "- Costco publishes vendor contact paths for prospective suppliers. [claim_vendor]\n"
            "- Costco identifies merchandise availability as an operating risk. [claim_supply]\n\n"
            "## What We Do Not Know\n"
            "- The supplier category, buyer team, geography, and timing are not identified.\n\n"
            "## Supplier/Buyer Angle\n"
            "Hypothesis to confirm: frame fit around member value and supply continuity. "
            "[claim_model] [claim_supply]\n\n"
            "## Questions to Ask\n"
            "- Which buying office, category, and region should the supplier prepare for? "
            "[claim_vendor]\n\n"
            "## Risks and Watchouts\n"
            "- Treat category priorities as open questions until the buyer confirms them.\n\n"
            "## Source Appendix\n"
            "- Costco vendor information (src_vendor) https://example.com/costco-vendor\n"
            "- Costco annual report (src_10k) https://example.com/costco-10k\n"
        ),
    )


def _ok_fetcher(url: str, timeout_seconds: float) -> SourceHttpResponse:
    return SourceHttpResponse(
        url=url,
        status_code=200,
        headers={"content-type": "text/html; charset=utf-8"},
        text=(
            "<html><head><title>Costco source</title></head><body><main>"
            "<p>Vendor inquiries may be directed to the applicable buying office.</p>"
            "<p>We operate membership warehouses based on value.</p>"
            "<p>Supply disruptions may affect merchandise availability.</p>"
            "</main></body></html>"
        ),
    )


def _forbidden_fetcher(url: str, timeout_seconds: float) -> SourceHttpResponse:
    return SourceHttpResponse(
        url=url,
        status_code=403,
        headers={"content-type": "text/html"},
        text="<html><body>Forbidden</body></html>",
    )


def _search_client(results: Sequence[SearchResult]) -> WebSearchClient:
    return WebSearchClient(provider=_AnyQuerySearchProvider(results))


def _search_results_for_sources(sources: Sequence[SourceCandidate]) -> list[SearchResult]:
    return [
        SearchResult(
            title=source.title,
            publisher=source.publisher,
            url=source.url,
            snippet=source.relevance_rationale,
            publication_date=source.publication_date,
        )
        for source in sources
    ]


def _status_check(actual: str, expected: str) -> RegressionCheck:
    return RegressionCheck(
        name="metadata_status",
        passed=actual == expected,
        detail=f"actual={actual}, expected={expected}",
    )


def _file_check(run_dir: Path, filename: str, *, should_exist: bool) -> RegressionCheck:
    actual = (run_dir / filename).exists()
    normalized = "report_md" if filename == "report.md" else Path(filename).stem
    return RegressionCheck(
        name=f"{normalized}_{'present' if should_exist else 'absent'}",
        passed=actual is should_exist,
        detail=f"{filename} exists={actual}, expected={should_exist}",
    )


def _metadata_file_check(run_dir: Path, expected_status: str) -> RegressionCheck:
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    actual = metadata.get("status")
    return RegressionCheck(
        name="metadata_json_status",
        passed=actual == expected_status,
        detail=f"metadata.json status={actual}, expected={expected_status}",
    )


def _base_success_runner(*, stale_claim: bool = False) -> Callable[[str, Any, str], Any]:
    def runner(agent_key: str, agent: Any, prompt: str) -> Any:
        if agent_key == "intake":
            return _charter()
        if agent_key == "planner":
            return _plan()
        if agent_key == "source_discovery":
            return SourceDiscoveryResult(sources=_direct_sources())
        if agent_key == "evidence_extraction":
            return EvidenceExtractionResult(claims=_direct_claims())
        if agent_key in {"competitor", "news", "risk"}:
            return SpecialistAnalysis(
                specialist=agent_key,
                summary="Source-bound analysis.",
                source_ids=["src_vendor"],
            )
        if agent_key == "synthesis":
            return _report(stale_claim=stale_claim)
        if agent_key == "qa":
            return QAReview(ready_to_publish=True, issues=[])
        raise AssertionError(f"Unexpected agent call: {agent_key}")

    return runner


def _scenario_full_qa_report_ready(runs_dir: Path) -> RegressionResult:
    with _patched_agent_set():
        result = orchestrator.run_research(
            "Research Costco before a supplier meeting",
            full=True,
            qa=True,
            mock=False,
            runs_dir=runs_dir,
            agent_runner=_base_success_runner(),
            source_fetcher=_ok_fetcher,
            search_client=_search_client(_search_results_for_sources(_direct_sources())),
        )
    run_dir = result.run_dir
    checks = [
        _status_check(result.metadata.status, "report_ready"),
        _metadata_file_check(run_dir, "report_ready"),
        _file_check(run_dir, "draft_report.md", should_exist=True),
        _file_check(run_dir, "report.md", should_exist=True),
        _file_check(run_dir, "qa_review.json", should_exist=True),
        _file_check(run_dir, "evidence_review.md", should_exist=False),
        _file_check(run_dir, "report_revision.md", should_exist=False),
    ]
    return RegressionResult(
        scenario_id="full_qa_report_ready",
        name="Full QA report-ready artifact contract",
        metadata_status=result.metadata.status,
        run_dir=run_dir,
        checks=checks,
    )


def _scenario_fallback_only_blocks(runs_dir: Path) -> RegressionResult:
    sources = [
        SourceCandidate(
            id="src_blocked",
            title="Costco investor relations overview",
            publisher="Costco Wholesale",
            url="https://example.com/costco-ir",
            source_type="investor_material",
            relevance_rationale="Investor page exists but direct fetch is blocked.",
            recommended_uses=["company updates"],
            bias_risk="medium",
            publication_date="2026-02-01",
        )
    ]

    def runner(agent_key: str, agent: Any, prompt: str) -> Any:
        if agent_key == "intake":
            return _charter()
        if agent_key == "planner":
            return _plan(["investor_material"])
        if agent_key == "source_discovery":
            return SourceDiscoveryResult(sources=sources)
        if agent_key == "evidence_extraction":
            payload = _json_payload_from_prompt(prompt)
            if payload["source_content"]:
                raise AssertionError("Fallback-only scenario should not have fetched content.")
            if not payload["weak_fallback_context"]:
                raise AssertionError("Fallback-only scenario should expose weak fallback context.")
            return EvidenceExtractionResult(
                claims=[
                    EvidenceClaim(
                        id="snippet_claim",
                        claim=(
                            "The investor page indicates Costco has a current "
                            "supplier strategy priority."
                        ),
                        claim_type="fact",
                        source_id="src_blocked",
                        source_url="https://example.com/costco-ir",
                        source_type="investor_material",
                        confidence="high",
                        report_section="Supplier/Buyer Angle",
                        quote_or_excerpt="Investor page exists but direct fetch is blocked.",
                    )
                ]
            )
        if agent_key in {"news", "risk", "synthesis", "qa"}:
            raise AssertionError(f"{agent_key} should not run for fallback-only evidence.")
        raise AssertionError(f"Unexpected agent call: {agent_key}")

    with _patched_agent_set():
        result = orchestrator.run_research(
            "Research Costco before a supplier meeting",
            full=True,
            qa=True,
            mock=False,
            runs_dir=runs_dir,
            agent_runner=runner,
            source_fetcher=_forbidden_fetcher,
            search_client=_search_client(_search_results_for_sources(sources)),
        )
    run_dir = result.run_dir
    fetch_log = json.loads((run_dir / "source_fetch_log.json").read_text(encoding="utf-8"))
    ledger = json.loads((run_dir / "evidence_ledger.json").read_text(encoding="utf-8"))
    checks = [
        _status_check(result.metadata.status, "evidence_needs_review"),
        _metadata_file_check(run_dir, "evidence_needs_review"),
        _file_check(run_dir, "evidence_review.md", should_exist=True),
        _file_check(run_dir, "draft_report.md", should_exist=False),
        _file_check(run_dir, "qa_review.json", should_exist=False),
        _file_check(run_dir, "report.md", should_exist=False),
        RegressionCheck(
            name="fallback_source_logged",
            passed=fetch_log["results"][0]["status"] == "fallback",
            detail=f"source_fetch_log status={fetch_log['results'][0]['status']}",
        ),
        RegressionCheck(
            name="fallback_claim_not_published",
            passed=all(claim["id"] != "snippet_claim" for claim in ledger["claims"]),
            detail=f"evidence claim IDs={[claim['id'] for claim in ledger['claims']]}",
        ),
    ]
    return RegressionResult(
        scenario_id="fallback_only_evidence_blocked",
        name="Fallback-only evidence stops before synthesis",
        metadata_status=result.metadata.status,
        run_dir=run_dir,
        checks=checks,
    )


def _scenario_indirect_only_blocks(runs_dir: Path) -> RegressionResult:
    sources = [
        SourceCandidate(
            id="src_industry",
            title="Retail industry overview",
            publisher="Industry Analyst",
            url="https://example.com/retail-industry",
            source_type="industry_primer",
            relevance_rationale="Indirect industry context.",
            recommended_uses=["market context"],
            bias_risk="medium",
            publication_date="2026-01-20",
        )
    ]

    def runner(agent_key: str, agent: Any, prompt: str) -> Any:
        if agent_key == "intake":
            return _charter()
        if agent_key == "planner":
            return _plan(["industry_primer"])
        if agent_key == "source_discovery":
            return SourceDiscoveryResult(sources=sources)
        if agent_key == "evidence_extraction":
            return EvidenceExtractionResult(
                claims=[
                    EvidenceClaim(
                        id="claim_indirect",
                        claim="Retail warehouse demand is linked to consumer value seeking.",
                        claim_type="fact",
                        source_id="src_industry",
                        source_url="https://example.com/retail-industry",
                        source_type="industry_primer",
                        confidence="medium",
                        report_section="Market Context",
                        quote_or_excerpt="Warehouse retail demand is linked to value seeking.",
                    )
                ]
            )
        if agent_key in {"news", "risk", "synthesis", "qa"}:
            raise AssertionError(f"{agent_key} should not run for indirect-only evidence.")
        raise AssertionError(f"Unexpected agent call: {agent_key}")

    with _patched_agent_set():
        result = orchestrator.run_research(
            "Research Costco before a supplier meeting",
            full=True,
            qa=True,
            mock=False,
            runs_dir=runs_dir,
            agent_runner=runner,
            source_fetcher=_ok_fetcher,
            search_client=_search_client(_search_results_for_sources(sources)),
        )
    run_dir = result.run_dir
    ledger = json.loads((run_dir / "evidence_ledger.json").read_text(encoding="utf-8"))
    checks = [
        _status_check(result.metadata.status, "evidence_needs_review"),
        _metadata_file_check(run_dir, "evidence_needs_review"),
        _file_check(run_dir, "evidence_review.md", should_exist=True),
        _file_check(run_dir, "draft_report.md", should_exist=False),
        _file_check(run_dir, "report.md", should_exist=False),
        RegressionCheck(
            name="direct_company_evidence_blocked",
            passed=any(
                DIRECT_EVIDENCE_SUFFICIENCY_WARNING in warning
                for warning in ledger["validation_warnings"]
            ),
            detail="direct-company evidence sufficiency warning is present",
        ),
    ]
    return RegressionResult(
        scenario_id="indirect_only_company_evidence_blocked",
        name="Indirect-only company evidence stops before synthesis",
        metadata_status=result.metadata.status,
        run_dir=run_dir,
        checks=checks,
    )


def _scenario_traceability_revision(runs_dir: Path) -> RegressionResult:
    with _patched_agent_set():
        result = orchestrator.run_research(
            "Research Costco before a supplier meeting",
            full=True,
            qa=True,
            mock=False,
            runs_dir=runs_dir,
            agent_runner=_base_success_runner(stale_claim=True),
            source_fetcher=_ok_fetcher,
            search_client=_search_client(_search_results_for_sources(_direct_sources())),
        )
    run_dir = result.run_dir
    revision = (run_dir / "report_revision.md").read_text(encoding="utf-8")
    checks = [
        _status_check(result.metadata.status, "draft_needs_revision"),
        _metadata_file_check(run_dir, "draft_needs_revision"),
        _file_check(run_dir, "draft_report.md", should_exist=True),
        _file_check(run_dir, "report_revision.md", should_exist=True),
        _file_check(run_dir, "qa_review.json", should_exist=False),
        _file_check(run_dir, "report.md", should_exist=False),
        RegressionCheck(
            name="unknown_claim_id_reported",
            passed="claim_stale" in revision,
            detail="report_revision.md names claim_stale",
        ),
    ]
    return RegressionResult(
        scenario_id="traceability_failure_revision",
        name="Unknown claim IDs create report revision artifact",
        metadata_status=result.metadata.status,
        run_dir=run_dir,
        checks=checks,
    )


def _scenario_continue_report_ready(runs_dir: Path) -> RegressionResult:
    with _patched_agent_set():
        checkpoint = orchestrator.run_research(
            "Research Costco before a supplier meeting",
            checkpoint_only=True,
            mock=False,
            runs_dir=runs_dir,
            agent_runner=_base_success_runner(),
            source_fetcher=_ok_fetcher,
            search_client=_search_client(_search_results_for_sources(_direct_sources())),
        )
        orchestrator.save_user_feedback(
            checkpoint.run_dir,
            UserFeedback(approved_source_ids=["src_vendor", "src_10k"]),
        )
        result = orchestrator.continue_research(
            checkpoint.run_dir,
            qa=True,
            mock=False,
            runs_dir=runs_dir,
            agent_runner=_base_success_runner(),
            source_fetcher=_ok_fetcher,
            search_client=_search_client(_search_results_for_sources(_direct_sources())),
        )
    run_dir = result.run_dir
    checks = [
        _status_check(result.metadata.status, "report_ready"),
        _metadata_file_check(run_dir, "report_ready"),
        _file_check(run_dir, "user_feedback.json", should_exist=True),
        _file_check(run_dir, "draft_report.md", should_exist=True),
        _file_check(run_dir, "report.md", should_exist=True),
        _file_check(run_dir, "qa_review.json", should_exist=True),
        _file_check(run_dir, "evidence_review.md", should_exist=False),
        _file_check(run_dir, "report_revision.md", should_exist=False),
    ]
    return RegressionResult(
        scenario_id="continue_report_ready",
        name="Continue workflow reaches report-ready with QA",
        metadata_status=result.metadata.status,
        run_dir=run_dir,
        checks=checks,
    )


SCENARIOS: list[Callable[[Path], RegressionResult]] = [
    _scenario_full_qa_report_ready,
    _scenario_fallback_only_blocks,
    _scenario_indirect_only_blocks,
    _scenario_traceability_revision,
    _scenario_continue_report_ready,
]


def results_to_dict(results: list[RegressionResult]) -> dict[str, Any]:
    passed_count = sum(1 for result in results if result.passed)
    scenario_count = len(results)
    return {
        "scenario_count": scenario_count,
        "passed_count": passed_count,
        "failed_count": scenario_count - passed_count,
        "all_passed": passed_count == scenario_count,
        "scenarios": [result.to_dict() for result in results],
    }


def render_scorecard(results: list[RegressionResult]) -> str:
    passed_count = sum(1 for result in results if result.passed)
    lines = [
        "# Regression Harness Scorecard",
        "",
        f"- Scenarios: {len(results)}",
        f"- Result: {passed_count}/{len(results)} scenarios passed",
        "",
        "| Scenario | Name | Status | Metadata | Run Dir |",
        "| --- | --- | --- | --- | --- |",
    ]
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        lines.append(
            "| "
            f"{result.scenario_id} | {result.name} | {status} | "
            f"{result.metadata_status} | {result.run_dir} |"
        )

    lines.extend(["", "## Scenario Details"])
    for result in results:
        lines.extend(["", f"### {result.scenario_id}", "", "- Checks:"])
        for check in result.checks:
            check_status = "PASS" if check.passed else "FAIL"
            lines.append(f"  - {check.name}: {check_status} - {check.detail}")

    failed = [result for result in results if not result.passed]
    if failed:
        lines.extend(["", "## Failures"])
        for result in failed:
            lines.append("")
            lines.append(f"### {result.scenario_id}")
            for check in result.checks:
                if not check.passed:
                    lines.append(f"- {check.name}: {check.detail}")

    return "\n".join(lines) + "\n"


def run(runs_dir: Path | None = None) -> tuple[list[RegressionResult], str]:
    output_runs_dir = runs_dir or (ROOT / "runs" / "eval_regression")
    output_runs_dir.mkdir(parents=True, exist_ok=True)
    results = [scenario(output_runs_dir) for scenario in SCENARIOS]
    return results, render_scorecard(results)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic workflow artifact regression scenarios."
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=ROOT / "runs" / "eval_regression",
        help="Directory where scenario run artifacts should be written.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write the markdown scorecard.",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help="Optional path to write machine-readable JSON results.",
    )
    args = parser.parse_args(argv)

    results, scorecard = run(args.runs_dir)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(scorecard, encoding="utf-8")
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(results_to_dict(results), indent=2) + "\n",
            encoding="utf-8",
        )
    print(scorecard, end="")
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
