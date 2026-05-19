# Roadmap — Phase 9 to Phase 14

This roadmap assumes the project has already completed:

- deterministic mock workflow
- live checkpoint workflow
- source discovery and scoring
- evidence ledger
- specialist agents
- report generation
- QA gate
- environment hardening
- duplicate evidence claim handling

The remaining work is about quality, durability, and usability.

---

# Phase 9 — Evidence and Artifact Quality Hardening

## Goal

Improve the quality and inspectability of the evidence ledger, draft report, QA review, and run artifacts.

## Why this matters

The live pipeline now runs, but QA still blocks the report because the draft makes broad claims without direct support. That means the system needs better evidence, not more agents.

## Scope

- near-duplicate evidence detection
- better evidence claim classification
- better QA issue taxonomy
- live-run review docs
- synthesis prompt tightening
- artifact review tooling

## Deliverables

```text
docs/live-smoke/phase-8-full-qa-smoke.md
src/agentic_research/evidence_quality.py
src/agentic_research/artifact_review.py
updated prompts/agents/synthesis_agent.md
updated prompts/agents/qa_agent.md
tests/test_evidence_quality.py
tests/test_artifact_review.py
```

## Acceptance criteria

- `make check` passes
- `make smoke-mock` passes
- live `--full --qa` run completes
- `qa_review.json` has structured issue categories
- near-duplicate evidence is detected or deduped
- report remains blocked if unsupported claims remain
- artifact review summary is generated for every live full run or via a command

---

# Phase 10 — Source Content Ingestion

## Goal

Move from "source URL discovery" to "source content-based evidence extraction."

## Why this matters

Search snippets cannot support serious research. The system needs actual text from filings, investor pages, earnings releases, PDFs, and vendor docs.

## Scope

- fetch source URLs
- parse HTML
- optionally parse PDFs
- save content artifacts
- chunk content
- extract evidence from chunks
- avoid huge downloads
- support source fetch failure states

## Deliverables

```text
src/agentic_research/source_ingestion.py
src/agentic_research/source_content.py
runs/<run_id>/source_content.json
runs/<run_id>/source_fetch_log.json
tests/test_source_ingestion.py
```

## Acceptance criteria

- top included sources are fetched
- content is saved
- evidence extraction uses content excerpts, not just snippets
- failed fetches are logged without crashing the run
- source excerpts are short and traceable

---

# Phase 11 — Report Quality and Template Discipline

## Goal

Make drafts more useful, less generic, and more aligned to the chosen research lens.

## Scope

- stronger meeting-prep template
- investment memo template
- industry primer template
- report section rubrics
- evidence-backed talking points
- explicit "not enough evidence" language
- section-specific citation/claim requirements

## Deliverables

```text
templates/meeting_prep.md
templates/company_brief.md
templates/industry_primer.md
templates/investment_memo.md
src/agentic_research/report_validation.py
tests/test_report_validation.py
```

## Acceptance criteria

- draft report cites claim IDs for material assertions
- unsupported claims are downgraded or omitted
- meeting prep includes: context, supplier angle, questions to ask, risks, open questions
- weak evidence produces cautious language, not invented confidence

---

# Phase 12 — Evaluation Harness

## Goal

Create repeatable research-quality evaluations.

## Scope

- fixture runs
- golden evidence ledgers
- golden QA reviews
- rubric-based scoring
- regression tests for report quality
- optional model-based evals

## Deliverables

```text
evals/
evals/fixtures/
evals/rubrics/
evals/run_eval.py
docs/EVALUATION.md
```

## Acceptance criteria

- can run local evals without live API calls
- at least three fixture requests:
  - company meeting prep
  - investment memo
  - industry primer
- quality gates cover source grounding, unsupported claims, evidence depth, report usefulness

---

# Phase 13 — User Checkpoint and Continue Workflow

## Goal

Make the gated workflow practical.

## Problem

The current CLI can produce checkpoint and full run artifacts, but it does not yet have a clean "continue from checkpoint with user preferences" workflow.

## Scope

- read an existing run
- store user answers
- continue from checkpoint
- allow source approval/rejection
- allow lens/depth override after checkpoint
- allow focused follow-up

## Deliverables

```text
arf continue <run_id>
arf runs
arf show <run_id>
arf approve-sources <run_id>
runs/<run_id>/user_feedback.json
```

## Acceptance criteria

- user can run checkpoint first
- user can answer checkpoint questions
- user can continue from the same run without restarting source discovery
- artifacts remain traceable

---

# Phase 14 — Production Readiness Foundation

## Goal

Prepare for a future web app or hosted workflow without building it prematurely.

## Scope

- CI
- structured logging
- run metadata schema
- cost/latency tracking
- model config
- optional artifact exports
- error handling

## Deliverables

```text
.github/workflows/ci.yml
src/agentic_research/logging.py
src/agentic_research/run_store.py
docs/PRODUCTION_READINESS.md
```

## Acceptance criteria

- CI runs tests, lint, and typecheck
- all local `make` commands documented
- live runs produce timing/cost placeholders
- artifact schema is stable enough for future UI
