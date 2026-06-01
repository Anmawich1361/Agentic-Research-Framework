# V1 Release Readiness

Status: V1 validation passed in this branch on 2026-06-01.

## Checklist

- CLI-first workflow remains the only product surface.
- No web app, database, auth, background job, scheduler, vector DB, PDF/DOCX
  export, or complex SEC parser was added.
- `--mock` mode remains deterministic.
- Run artifacts remain under `runs/<run_id>/`.
- `report.md` remains gated on requested QA, successful pre-QA validation, QA
  execution, and zero high-severity QA issues.
- Failed, skipped, and fallback-only source fetches remain visible and blocked
  from ordinary factual synthesis.
- Current/recent claims require dated direct evidence or an explicit caveat.
- `arf review-run <run_id>` provides a compact operator summary and refreshes
  `artifact_review.md`.

## Required Validation

```text
make doctor: passed
make check: passed, 156 tests passed; Ruff passed; mypy passed
make eval: passed, 10/10 fixtures
make eval-regression: passed, 5/5 scenarios
make smoke-mock: passed, run_20260601T142504Z_0d3e5333
git diff --check: passed
```

Mock smoke artifact inspection for `run_20260601T142504Z_0d3e5333`:

- `metadata.status`: `checkpoint_ready`
- `metadata.run_type`: `checkpoint`
- artifacts present: `metadata.json`, `charter.json`, `research_plan.json`,
  `sources.json`, `source_map.json`, `checkpoint.md`, and `run_log.jsonl`

## Accepted Limitations

- Live source retrieval is still bounded and can be blocked by external sites,
  PDFs, SSL issues, SEC access limits, or bot protection.
- The framework exposes source gaps and evidence gaps as statuses and review
  artifacts; it does not guarantee every live report will publish.
- Report quality can still receive non-blocking medium/low QA caveats around
  recency, specificity, or user context.
- Operator review remains filesystem-based through CLI summaries and artifacts.
