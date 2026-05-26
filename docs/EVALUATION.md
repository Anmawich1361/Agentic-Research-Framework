# Evaluation

The evaluation harness provides repeatable local checks for research output
quality and workflow safety. Evals are deterministic by default: they load saved
fixtures or fake-agent workflows and run local validation/rubric checks only.
They do not call live OpenAI APIs or fetch the web.

## How To Run

Use the Makefile target for normal quality-fixture validation:

```bash
make eval
```

The target runs:

```bash
.venv/bin/python evals/run_eval.py
```

Run workflow artifact regressions separately:

```bash
make eval-regression
```

The target runs:

```bash
.venv/bin/python evals/run_regression.py
```

You can also run the scripts directly:

```bash
.venv/bin/python evals/run_eval.py
.venv/bin/python evals/run_regression.py
```

Optional outputs:

```bash
.venv/bin/python evals/run_eval.py \
  --output runs/eval_scorecard.md \
  --json-output runs/eval_results.json

.venv/bin/python evals/run_regression.py \
  --output runs/eval_regression_scorecard.md \
  --json-output runs/eval_regression_results.json
```

Files under `runs/` are ignored by git.

The markdown scorecards print fixture or scenario name, pass/fail status,
rubric-level check results, and actionable failure details. JSON output is
machine-readable and includes check details plus failure reasons for CI/Codex
review.

## Quality Fixtures

Fixtures live in `evals/fixtures/` and are loaded by `evals/run_eval.py`.

Current publishable fixtures:

- `company_meeting_prep.json`: supplier-meeting brief with meeting-prep
  sections, evidence gaps, and source-grounded recommendations.
- `industry_primer.json`: industry-primer report with definition, value chain,
  demand drivers, risks, and open questions.
- `investment_memo.json`: investment memo with business overview, market
  context, financial/operating profile, competitive landscape, risks, and open
  diligence questions.
- `strong_source_grounded_report.json`: source-grounded investment report
  across primary company, filing, investor, and industry evidence.
- `thin_conservative_meeting_prep.json`: thin but conservative meeting-prep
  report that passes only because it states evidence limitations explicitly.

Current expected-blocking fixtures:

- `unsupported_recent_strategy_claims.json`: current/recent strategy claims
  must fail when direct evidence is missing.
- `fallback_snippet_evidence_blocked.json`: fallback-only or search-snippet
  evidence must be sanitized out before it can support report claims.
- `indirect_only_company_evidence_blocked.json`: company reports must block
  before synthesis when only indirect industry/news evidence remains.
- `stale_unknown_claim_ids.json`: reports must fail traceability when they cite
  unknown or stale claim IDs.

Expected-bad fixtures pass the eval only when the expected guardrail fires. If a
future change weakens the guardrail, the fixture fails.

Each fixture contains:

- `id` and `name`
- `request`
- `template_name`
- `source_map`
- `evidence_ledger`
- `draft_report`
- `expected_qa`
- `expected_report_sections`

Fixtures can also include:

- `source_fetch_log`, when evidence sanitization depends on fetch status.
- `charter`, when target type matters for a pre-synthesis evidence gate.
- `expected_evidence`, when the fixture should assert blocked claim IDs,
  validation warnings, or blocking evidence status.

## Rubrics

Rubric descriptions live in `evals/rubrics/`. The quality runner currently
checks:

- `source_grounding`: report claims and source references must trace to known
  evidence claim IDs and known source IDs, unless the fixture explicitly expects
  a grounding failure.
- `evidence_depth`: evidence claim count must meet the fixture minimum.
- `unsupported_claims`: broad or material claims must be cited, caveated, or
  expected as a guardrail failure.
- `report_usefulness`: expected report sections must be present for the
  selected template and user request.
- `recency_handling`: fixtures requiring recent context must include dated
  sources and avoid stale/unclear recency issues.
- `source_diversity`: distinct claim source IDs must meet the fixture minimum.

The runner also records QA severity limits, minimum issue counts,
required/forbidden QA categories, evidence claim IDs, evidence validation
warnings, failed checks, and failure reasons.

## Regression Scenarios

`evals/run_regression.py` runs deterministic mocked workflows through
`run_research` and `continue_research` with fake agents, fake search results,
and fake source fetchers.

It verifies:

- `metadata.status` for report-ready, evidence-blocked, and revision-blocked
  paths.
- Expected artifacts exist or do not exist.
- `report.md` is written only after QA passes.
- `evidence_review.md` appears for blocking evidence gaps.
- `report_revision.md` appears for deterministic traceability failures.
- fallback-only evidence remains blocked and never reaches published report
  artifacts.

The current regression scenarios are:

- `full_qa_report_ready`
- `fallback_only_evidence_blocked`
- `indirect_only_company_evidence_blocked`
- `traceability_failure_revision`
- `continue_report_ready`

Failure output lists the scenario, run directory, failed check name, and concrete
reason so CI and future Codex runs can inspect the exact artifact contract that
changed.

## Adding A Fixture

1. Add a new JSON file under `evals/fixtures/`.
2. Use a stable `id` and clear `name`.
3. Include a realistic `source_map`, `evidence_ledger`, and `draft_report`.
4. Set `expected_report_sections` to the headings the report should contain.
5. Set `expected_qa` thresholds, including source and claim count minimums.
6. If the fixture intentionally blocks, make the expected failure explicit with
   required categories, minimum issue counts, or `expected_evidence`.
7. Run `make eval`.

Fixtures should stay small, deterministic, and local. Do not depend on API keys,
network fetches, live search results, or generated `runs/` artifacts.

## Evals vs Pytest

`pytest` verifies code behavior: models, orchestrator paths, validation helpers,
CLI behavior, and deterministic artifact writing.

The eval harness verifies report-quality expectations and workflow safety
against curated examples. It is closer to a scorecard than a unit test: each
fixture or scenario runs multiple checks and returns a pass/fail score plus
actionable failure messages.

Both should stay deterministic. Use pytest for implementation regressions,
`make eval` for report-quality regressions, and `make eval-regression` for
end-to-end artifact publication contracts.

## Current Weak Spots

The current rubrics are still intentionally lightweight. They are useful for
catching traceability, section, source-count, fallback-evidence, direct-company
evidence, and obvious unsupported-claim regressions, but they do not yet judge
nuanced narrative quality, source freshness beyond `publication_date` presence,
or subtle evidence strength. Future report-quality work should improve those
rubric dimensions with additional fixtures and more specific deterministic
checks.
