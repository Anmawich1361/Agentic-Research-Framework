# Evaluation Harness

This directory contains deterministic evals for research-output quality.

Run:

```bash
make eval
```

The runner loads JSON fixtures from `evals/fixtures/`, runs deterministic QA and report-validation checks, and prints a markdown scorecard. It does not call live APIs.

Workflow artifact regressions are separate:

```bash
make eval-regression
```

That command runs deterministic fake-agent `run_research` and `continue_research`
scenarios and verifies status plus artifact publication rules.

Fixtures should include:

- `request`
- `source_map`
- `evidence_ledger`
- `draft_report`
- `expected_qa`
- `expected_report_sections`

Fixtures can also include `source_fetch_log`, `charter`, and
`expected_evidence` when the scenario is expected to block before synthesis.
Expected-bad fixtures pass only when the expected guardrail fires.

Rubrics live in `evals/rubrics/` and correspond to the scorecard checks.

See `docs/EVALUATION.md` for the scenario inventory and failure interpretation.
