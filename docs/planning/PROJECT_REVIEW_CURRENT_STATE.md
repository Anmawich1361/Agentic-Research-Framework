# Project Review — Current State

## Executive assessment

The Agentic Research Framework has moved from a static scaffold to a working CLI-based live research pipeline. The system can now:

- create a research charter
- generate a research plan
- discover and score sources
- write a checkpoint
- extract evidence
- run specialist analysis
- synthesize a draft
- run QA
- block final publication when QA finds high-severity issues

The main conclusion: **the pipeline now runs, but the output quality is not yet reliable enough for user-facing final reports.**

The next work should focus on **evidence quality, real source ingestion, report grounding, and evaluation**, not more agents.

---

## What is working

### 1. CLI-first project structure

The project has a functional CLI and local artifact model. Runs are saved under:

```text
runs/<run_id>/
```

Current artifacts can include:

```text
metadata.json
charter.json
research_plan.json
sources.json
source_map.json
evidence_ledger.json
specialist_analyses.json
draft_report.md
qa_review.json
report.md
checkpoint.md
```

### 2. Local development workflow

The developer environment has been hardened with:

```text
make reset-env
make doctor
make check
make smoke-mock
make smoke-live-checkpoint
```

This was necessary because the project uses a `src/` layout, and the package must be installed in editable mode for `agentic_research` and `.venv/bin/arf` to work reliably.

### 3. Live checkpoint works

A live checkpoint run works and produces useful initial artifacts. The checkpoint flow correctly distinguishes live mode from mock mode after the source-map wording fix.

### 4. Live full QA path runs

The live `--full --qa` path now reaches QA. This proves the basic orchestration path is functioning:

```text
intake
→ planning
→ source discovery
→ source scoring
→ evidence extraction
→ specialist analysis
→ evidence merge
→ synthesis
→ QA
→ publication gate
```

### 5. Final report gating works

The system correctly prevents `report.md` from being written when QA returns high-severity issues. This is the correct behavior.

### 6. Evidence duplicate ID handling improved

The project now detects duplicate evidence claim IDs, deduplicates identical claims, renames conflicting specialist claim IDs, blocks conflicting base duplicates, and writes `evidence_review.md` when evidence validation prevents synthesis.

---

## What is not working well enough yet

### 1. Evidence is shallow

The current live run can generate an evidence ledger, but the claims are often source-descriptive rather than research-substantive.

Example of weak evidence type:

```text
"Costco's investor relations site is a primary hub..."
```

This is true but not a meaningful business insight. The next version should extract facts from actual source content, not just source metadata and search snippets.

### 2. Report claims can still be too generic

QA correctly blocked a Costco supplier-meeting draft because the report made broad supplier-priority claims without strong evidence. That means the QA gate is working, but the synthesis prompt and evidence extraction are not yet producing sufficiently grounded outputs.

### 3. Source discovery lacks real document ingestion

The current source discovery layer finds URLs and classifies sources, but it does not reliably fetch and parse the source documents themselves. This is why evidence is thin.

For a true research system, the pipeline needs:

```text
source discovery
→ source content fetch
→ source content extraction
→ chunking
→ evidence extraction from content
```

### 4. Source quality is too dependent on search result snippets

Search snippets are useful for source discovery, but not enough for serious research. Corporate filings, earnings releases, vendor documents, and PDFs need to be fetched and parsed before they can support factual claims.

### 5. Orchestrator is too large

`orchestrator.py` now controls too many responsibilities:

- run creation
- agent prompts
- source scoring flow
- evidence validation
- duplicate handling
- specialist orchestration
- report repair
- QA
- artifact writing

This is acceptable for the prototype, but it should be split before further complexity is added.

### 6. QA is directionally useful but not systematic enough

QA can identify high-severity issues, but the deterministic QA layer is still basic. The system needs more structured QA categories:

```text
unsupported_claim
weak_source
missing_recent_signal
overconfident_inference
source_gap
stale_or_unclear_recency
missing_user_context
report_structure_issue
```

### 7. There is no evaluation harness

Tests verify code behavior, but not research quality. The next version needs repeatable eval fixtures and golden runs.

---

## Current maturity level

| Area | Status |
|---|---|
| Repo scaffold | Done |
| CLI | Working |
| Mock workflow | Working |
| Local dev workflow | Working |
| Live checkpoint | Working |
| Live full draft | Working |
| Live QA gate | Working |
| Evidence ledger | Functional but shallow |
| Source discovery | Functional but source-content-light |
| Report quality | Not yet acceptable |
| QA quality | Useful but incomplete |
| Evaluation harness | Missing |
| CI | Missing or not relied upon |
| Document ingestion | Missing |
| Persistence/database | Not needed yet |
| Web UI | Not needed yet |

---

## Recommended next priority

Do not add a web UI, database, or more specialist agents yet.

The next phase should be:

```text
Phase 9 — Evidence and artifact quality hardening
```

Goal:

```text
Turn live runs from "pipeline completed" into "artifact quality is understandable, inspectable, and improving."
```

The system should produce a better evidence ledger before attempting to improve the final report.

---

## Immediate acceptance criteria for next phase

A good Phase 9 should make the next live Costco run produce:

1. fewer duplicate or near-duplicate evidence claims
2. clearer distinction between facts and inferences
3. fewer generic "source page exists" claims
4. stronger QA issue categories
5. a live smoke summary document under `docs/live-smoke/`
6. no final `report.md` unless QA passes
7. a draft report that explicitly says when evidence is thin
