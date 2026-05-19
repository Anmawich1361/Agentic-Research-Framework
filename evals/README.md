# Evaluation Harness

This directory contains deterministic evals for research-output quality.

Run:

```bash
python evals/run_eval.py
```

The runner loads JSON fixtures from `evals/fixtures/`, runs deterministic QA and report-validation checks, and prints a markdown scorecard. It does not call live APIs.

Fixtures should include:

- `request`
- `source_map`
- `evidence_ledger`
- `draft_report`
- `expected_qa`
- `expected_report_sections`

Rubrics live in `evals/rubrics/` and correspond to the scorecard checks.
