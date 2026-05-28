# Artifact Contract

All workflow artifacts are written under:

```text
runs/<run_id>/
```

The artifact set depends on how far the workflow gets. Absence of a later-stage
artifact is meaningful and should be interpreted with `metadata.json.status`.
For status meanings, report publication expectations, and next actions, see
the [Run Status Contract](RUN_STATUS.md).

## Checkpoint Artifacts

Checkpoint runs write:

- `metadata.json`: run identity, timing, mode, lens, mock/live flag, status, and
  status reason.
- `charter.json`: structured research charter.
- `research_plan.json`: structured research plan.
- `sources.json`: source candidates discovered by mock or live source discovery.
- `source_map.json`: scored source map with source scores, included sources,
  gaps, and notes.
- `checkpoint.md`: user-facing checkpoint summary for approval or steering.
- `run_log.jsonl`: structured event log for stages, tools, agent calls,
  artifacts, and errors.

Optional checkpoint-continuation artifact:

- `user_feedback.json`: saved answers, approved/rejected sources, priority
  topics, and user notes used by `arf continue`.

## Full-Run Artifacts

Full runs can add:

- `source_content.json`: fetched and cleaned source text, excerpts, and bounded
  chunks used for evidence extraction.
- `source_fetch_log.json`: fetch status for each source URL, including failed or
  skipped fetches.
- `evidence_ledger.json`: final evidence claims after deduplication,
  evidence-quality filtering, confidence downgrades, and specialist claim merge.
- `specialist_analyses.json`: specialist summaries, cited source IDs, and any
  specialist-proposed evidence claims.
- `draft_report.md`: synthesized draft report when evidence and pre-QA report
  validation allow a draft to be written.
- `artifact_review.md`: summary of present/missing artifacts, evidence counts,
  source-fetch counts, blocking warnings, QA issue counts, publication status,
  and recommended next action.

## QA Artifacts

QA runs can add:

- `qa_review.json`: deterministic and model QA findings after a draft reaches
  QA. High-severity issues block final publication.
- `report.md`: final markdown report. This is written only when QA is requested
  and passes without high-severity issues.

If QA is not requested, a draft may exist without `qa_review.json` or
`report.md`. That state is normally `draft_needs_qa`.

## Source Ingestion Artifacts

Source ingestion runs before evidence extraction in full live workflows.

- `source_content.json` is the extracted content artifact. It stores
  `source_id`, `url`, `content_type`, `title`, full `text`, `excerpt`, and
  `chunks` for fetched source material that downstream evidence extraction can
  use. The chunks are bounded; this is not a full archive of every remote
  document.
- `source_fetch_log.json` is a lightweight operational log. It records
  `source_id`, `url`, `status`, `content_type`, `title`, `error`,
  `failure_reason`, `text_char_count`, `chunk_count`, optional `excerpt`, and
  optional `fetched_url` for redirects. `fallback` status means page fetch did
  not produce readable source text, but weak search-result context was retained
  for evidence extraction caveats.
- `source_fetch_log.json` must not duplicate full extracted text or full chunk
  lists. If downstream research needs text or chunks, it should read
  `source_content.json`.

Evidence extraction should prefer `source_content.json` chunks over source-map
metadata or search snippets. Snippet-only fallback context is weak and should
not support high-confidence claims.

## Review and Diagnostic Artifacts

- `artifact_review.md`: generated when evidence, report, or QA artifacts are
  present, and can be refreshed with `arf review-run <run_id>`. The CLI also
  prints the same high-level operator summary: status, publication state,
  final-report state, QA severity counts, source-fetch counts, blocking
  warnings, and next action.
- `evidence_review.md`: written when evidence validation has blocking warnings
  and synthesis/QA do not run.
- `report_revision.md`: written when deterministic pre-QA report validation
  fails, for example unknown claim/source references or missing required
  sections. QA does not run in this state.
- `error.json`: structured error details for a failed run.
- `failure_report.md`: human-readable failure report for a run that raised an
  exception before normal completion.

## Publication Contract

`report.md` is the only final report artifact. It must not be written merely
because `draft_report.md` exists.

Final publication requires:

- evidence validation did not produce blocking warnings,
- synthesis produced a traceable draft,
- pre-QA report validation passed,
- QA was requested and ran,
- QA found no high-severity issues.

When any gate blocks, the run should keep the narrowest useful diagnostic
artifact and avoid writing `report.md`.

## Status Contract

`metadata.json.status` is authoritative. Consumers should read it before using
artifact presence to infer workflow state. Current statuses are documented in
the [Run Status Contract](RUN_STATUS.md), including `checkpoint_ready`,
`evidence_ready`, `evidence_needs_review`, `draft_needs_qa`,
`draft_needs_revision`, `needs_review`, `report_ready`, and `failed`.
