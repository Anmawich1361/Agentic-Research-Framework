# Evaluation

The evaluation harness provides repeatable local checks for research output
quality. Evals are deterministic by default: they load saved fixtures and run
local validation/rubric checks only. They do not call live OpenAI APIs or fetch
the web.

## How To Run

Use the Makefile target for normal local validation:

```bash
make eval
```

The target runs:

```bash
.venv/bin/python evals/run_eval.py
```

You can also run the script directly:

```bash
.venv/bin/python evals/run_eval.py
```

Optional outputs:

```bash
.venv/bin/python evals/run_eval.py --output /tmp/eval_scorecard.md
.venv/bin/python evals/run_eval.py --json-output /tmp/eval_results.json
```

The markdown scorecard prints fixture name, pass/fail, total score, QA issue
counts, rubric-level check results, and actionable failure details. The JSON
output is machine-readable and includes fixture results, check details, QA issue
counts, QA issue categories, and QA issue payloads.

## Fixtures

Fixtures live in `evals/fixtures/`.

Current fixtures:

- `company_meeting_prep.json`: supplier-meeting brief with meeting-prep
  sections, evidence gaps, and source-grounded recommendations.
- `industry_primer.json`: industry-primer report with definition, value chain,
  demand drivers, risks, and open questions.
- `investment_memo.json`: investment memo with business overview, market
  context, financial/operating profile, competitive landscape, risks, and open
  diligence questions.

Each fixture contains:

- `id` and `name`
- `request`
- `template_name`
- `source_map`
- `evidence_ledger`
- `draft_report`
- `expected_qa`
- `expected_report_sections`

## Rubrics

Rubric descriptions live in `evals/rubrics/`. The runner currently checks:

- `source_grounding`: report claims and source references must trace to known
  evidence claim IDs and known source IDs.
- `evidence_depth`: evidence claim count must meet the fixture minimum.
- `unsupported_claims`: broad or material claims must be cited or caveated.
- `report_usefulness`: expected report sections must be present for the
  selected template and user request.
- `recency_handling`: fixtures requiring recent context must include dated
  sources and avoid stale/unclear recency issues.
- `source_diversity`: distinct claim source IDs must meet the fixture minimum.

The runner also records QA severity limits and required/forbidden QA
categories from `expected_qa`.

## Adding A Fixture

1. Add a new JSON file under `evals/fixtures/`.
2. Use a stable `id` and clear `name`.
3. Include a realistic `source_map`, `evidence_ledger`, and `draft_report`.
4. Set `expected_report_sections` to the headings the report should contain.
5. Set `expected_qa` thresholds, including source and claim count minimums.
6. Run `make eval`.
7. If the fixture intentionally fails, make the expected failure explicit with
   required categories or thresholds so future regressions are readable.

Fixtures should stay small, deterministic, and local. Do not depend on API keys,
network fetches, live search results, or generated `runs/` artifacts.

## Evals vs Pytest

`pytest` verifies code behavior: models, orchestrator paths, validation helpers,
CLI behavior, and deterministic artifact writing.

The eval harness verifies report-quality expectations against curated examples.
It is closer to a scorecard than a unit test: each fixture runs multiple rubric
checks and returns a pass/fail score plus actionable failure messages.

Both should stay deterministic. Use pytest for implementation regressions and
`make eval` for report-quality regressions.

## Current Weak Spots

The current rubrics are intentionally lightweight. They are useful for catching
traceability, section, source-count, and obvious unsupported-claim regressions,
but they do not yet judge narrative quality, source freshness beyond
`publication_date` presence, or nuanced evidence strength. Future report-quality
work should improve those rubric dimensions with additional fixtures and more
specific deterministic checks.
