# Production Readiness Foundation

Phase 14 adds the baseline artifacts needed for future hosted use without adding a web app or database.

For the V1 CLI release checklist and final validation record, see
[`RELEASE_READINESS.md`](RELEASE_READINESS.md).

## CI

GitHub Actions runs `.github/workflows/ci.yml` on pushes, pull requests, and manual dispatch. The workflow installs the package with `make setup` and runs `make check`. It does not run live smoke tests or require API keys.

## Run Metadata

Every completed run writes `metadata.json` with stable lifecycle fields:

- `run_id`
- `created_at`
- `started_at`
- `completed_at`
- `duration_seconds`
- `request`
- `status`
- `status_reason`
- `mode`
- `lens`
- `mock`
- `model`
- `run_type`

`run_type` is one of `checkpoint`, `full`, or `continue`.

## Structured Logging

Each run writes `run_log.jsonl` in the run directory. The log is append-only JSON Lines with one structured event per line. Current event types include:

- `stage_start`
- `stage_end`
- `agent_call`
- `tool_call`
- `artifact_written`
- `error`

The log is local-only and intended for debugging, hosted UI timelines, and future artifact viewers.

## Failure Artifacts

Major run failures write inspectable artifacts before re-raising the error:

- `metadata.json` with `status: failed`
- `error.json`
- `failure_report.md`
- `run_log.jsonl`

Failed runs do not write a new final `report.md`. Drafts and intermediate artifacts may exist only if they were successfully written before the failure.

## Artifact Contract

Future hosted surfaces should treat the run directory as the durable contract. UI code should read artifacts by name and handle missing files explicitly instead of inferring state from file existence alone. `metadata.status` and `metadata.status_reason` are the primary status fields.
