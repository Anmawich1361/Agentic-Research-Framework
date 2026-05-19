# Agentic Research Framework

Python CLI-first agentic research framework for company and industry research.
The framework turns a user research request into a charter, source map,
checkpoint, evidence ledger, cited markdown draft, and QA-gated final report.

## Current Status

The project has a working CLI pipeline with deterministic mock mode and live
agent mode. Current supported workflow stages are:

1. Intake
2. Research charter
3. Source discovery
4. Source scoring
5. User checkpoint
6. Source ingestion
7. Evidence extraction
8. Specialist analysis
9. Evidence deduplication and quality filtering
10. Synthesis
11. Pre-QA report validation
12. QA review
13. Final report publication when QA passes

Final report publication is intentionally gated. `report.md` is written only
when QA is requested, QA runs, and there are no high-severity QA issues.

For the post-PR #5 and PR #6 state, see
[`docs/CURRENT_STATUS.md`](docs/CURRENT_STATUS.md).

## Setup

Use the Makefile targets instead of manually setting `PYTHONPATH`.

```bash
make reset-env
make doctor
make check
```

`make reset-env` rebuilds `.venv` and installs the package in editable mode.
`make doctor` verifies the local interpreter, package import path, CLI entry
point, and boolean `.env` / `OPENAI_API_KEY` status. `make check` runs tests,
Ruff, and mypy.

After switching branches, this is usually enough:

```bash
make setup
make doctor
```

## CLI Commands

Run a deterministic mock checkpoint:

```bash
.venv/bin/arf run "Research Nvidia before an investor meeting" --mock --checkpoint-only
```

Run a live checkpoint:

```bash
./scripts/load_env_and_run.sh .venv/bin/arf run "Research Costco before a supplier meeting" --checkpoint-only --mode brief --lens sales
```

Run a live full workflow without QA:

```bash
./scripts/load_env_and_run.sh .venv/bin/arf run "Research Costco before a supplier meeting" --full --mode brief --lens sales
```

Run a live full workflow with QA:

```bash
./scripts/load_env_and_run.sh .venv/bin/arf run "Research Costco before a supplier meeting" --full --qa --mode brief --lens sales
```

List saved runs:

```bash
.venv/bin/arf runs
```

Show artifacts for one run:

```bash
.venv/bin/arf show <run_id>
```

Write or refresh an artifact review:

```bash
.venv/bin/arf review-run <run_id>
```

Continue from a checkpoint after adding user feedback:

```bash
.venv/bin/arf add-feedback <run_id> --note "Focus on supplier onboarding."
.venv/bin/arf continue <run_id> --qa
```

## Smoke Checks

Mock smoke:

```bash
make smoke-mock
```

Live checkpoint smoke:

```bash
make smoke-live-checkpoint
```

Live full QA smoke:

```bash
./scripts/load_env_and_run.sh .venv/bin/arf run "Research Costco before a supplier meeting" --full --qa --mode brief --lens sales
```

Live commands require `.env` with `OPENAI_API_KEY`. The helper script loads the
key without printing secret values.

## Artifact Outputs

Run artifacts are saved under:

```text
runs/<run_id>/
```

Checkpoint runs write the core planning/source artifacts:

- `metadata.json`
- `charter.json`
- `research_plan.json`
- `sources.json`
- `source_map.json`
- `checkpoint.md`
- `run_log.jsonl`

Full runs can also write:

- `source_content.json`
- `source_fetch_log.json`
- `evidence_ledger.json`
- `specialist_analyses.json`
- `draft_report.md`
- `artifact_review.md`

QA runs can also write:

- `qa_review.json`
- `report.md`, only when final QA gates pass
- `report_revision.md`, when pre-QA report validation fails
- `evidence_review.md`, when evidence validation blocks synthesis

Failed runs write:

- `error.json`
- `failure_report.md`

See [`docs/ARTIFACT_CONTRACT.md`](docs/ARTIFACT_CONTRACT.md) for the artifact
contract.

## Quality-Gate Behavior

The system should not publish fluent but unsupported prose.

Current gates:

- Evidence validation blocks synthesis for unsupported facts, unknown sources,
  and conflicting base duplicate claim IDs.
- Evidence deduplication and quality filtering run before synthesis.
- Synthesis receives `allowed_claim_ids` from the final evidence ledger and
  should cite only those IDs.
- Pre-QA report validation blocks drafts that cite unknown claim/source IDs or
  miss required sections.
- QA blocks final publication when high-severity issues remain.

When QA blocks, `draft_report.md` and `qa_review.json` are retained for review,
but `report.md` is not written.

## Current Limitations

- Source ingestion is intentionally simple and bounded; complex SEC/PDF parsing
  is not implemented.
- Search and source fetch quality can limit evidence depth.
- Draft quality can still be blocked by content QA even when claim-ID integrity
  is valid.
- The orchestrator remains large and will need refactoring before broad feature
  expansion.
- There is no web app, database, authentication, background job system,
  scheduler, vector database, or document export workflow.

## Planning Archive

Planning docs live under [`docs/planning/`](docs/planning/). Historical kickoff
material lives under [`docs/archive/`](docs/archive/).
