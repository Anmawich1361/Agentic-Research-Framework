# Run Status Contract

`metadata.json` is the authoritative place to read run status. A consumer should
use `metadata.status` to choose the next action and then read the artifacts that
match that status.

## `checkpoint_ready`

Meaning: Checkpoint artifacts were written and the run is waiting for user
feedback, approval, or a later full/continue command.

Expected artifacts: `metadata.json`, `charter.json`, `research_plan.json`,
`sources.json`, `source_map.json`, `checkpoint.md`, and `run_log.jsonl`.

`report.md`: Should not exist.

Next action: Review `checkpoint.md`, answer checkpoint questions or approve
sources, then run `arf continue` or rerun with `--full`.

## `evidence_ready`

Meaning: Evidence has been extracted and validated without blocking warnings,
and the run is ready for synthesis. This is mostly an internal or transitional
status; successful full runs usually continue into draft generation.

Expected artifacts: checkpoint artifacts plus `source_content.json`,
`source_fetch_log.json`, `evidence_ledger.json`, and `run_log.jsonl`.

`report.md`: Should not exist.

Next action: Continue synthesis if the run stopped here; otherwise inspect
`evidence_ledger.json` for traceability before drafting.

## `evidence_needs_review`

Meaning: Evidence validation produced blocking warnings, so synthesis and QA
were not run.

Expected artifacts: checkpoint artifacts plus `source_content.json`,
`source_fetch_log.json`, `evidence_ledger.json`, `evidence_review.md`,
`artifact_review.md`, and `run_log.jsonl`. `specialist_analyses.json` may also
exist if specialists ran before the blocker was detected.

`report.md`: Should not exist.

Next action: Read `evidence_review.md` and `evidence_ledger.json`, then fix the
evidence issue before attempting synthesis again.

## `draft_needs_qa`

Meaning: A draft report was written, but QA was not requested or has not
approved final publication.

Expected artifacts: checkpoint artifacts plus full-run artifacts including
`evidence_ledger.json`, `specialist_analyses.json` when specialists ran,
`draft_report.md`, `artifact_review.md`, and `run_log.jsonl`.

`report.md`: Should not exist.

Next action: Run the same research path with QA enabled, or inspect
`draft_report.md` before requesting QA.

## `draft_needs_revision`

Meaning: Deterministic pre-QA report validation failed. This commonly means the
draft cited unknown claim IDs, unknown source IDs, or missed required report
sections. QA was not run.

Expected artifacts: checkpoint artifacts plus `evidence_ledger.json`,
`draft_report.md`, `report_revision.md`, `artifact_review.md`, and
`run_log.jsonl`. `qa_review.json` should not exist because QA did not run.

`report.md`: Should not exist.

Next action: Read `report_revision.md`, fix the draft or synthesis inputs, and
rerun before QA.

## `needs_review`

Meaning: QA ran and found blocking issues, usually high-severity evidence,
source-quality, or report-quality issues. Final publication was blocked.

Expected artifacts: checkpoint artifacts plus full-run artifacts,
`draft_report.md`, `qa_review.json`, `artifact_review.md`, and `run_log.jsonl`.

`report.md`: Should not exist.

Next action: Read `qa_review.json` and `artifact_review.md`, address the
high-severity blockers, then rerun QA.

## `report_ready`

Meaning: QA passed and the final report was written.

Expected artifacts: checkpoint artifacts plus full-run artifacts,
`draft_report.md`, `qa_review.json`, `report.md`, `artifact_review.md`, and
`run_log.jsonl`.

`report.md`: Should exist.

Next action: Use `report.md` as the final QA-gated output. Keep
`draft_report.md` and `qa_review.json` for auditability.

## `failed`

Meaning: The run raised an exception before successful completion.

Expected artifacts: `metadata.json`, `error.json`, `failure_report.md`, and
`run_log.jsonl`. Other artifacts may exist if they were written before the
failure.

`report.md`: Should not exist as a new final report.

Next action: Read `failure_report.md`, `error.json`, and `run_log.jsonl`, fix
the failure, then rerun.
