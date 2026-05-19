# Quality Gates and Evaluation Plan

## Core principle

The project should never publish a final report merely because the model wrote fluent prose.

Final publication requires:

```text
evidence-backed claims
+ traceable source IDs
+ QA review
+ no high-severity QA issues
```

---

# Current gates

## Gate 1 — Local environment

Command:

```bash
make doctor
```

Expected:

- package imports from `src/agentic_research`
- `.venv/bin/arf --help` works
- `.env` exists for live runs
- API key status is printed as boolean only

## Gate 2 — Static checks

Command:

```bash
make check
```

Expected:

- tests pass
- ruff passes
- mypy passes

## Gate 3 — Mock smoke

Command:

```bash
make smoke-mock
```

Expected:

- mock checkpoint run completes
- run artifacts are written
- no live API calls

## Gate 4 — Live checkpoint

Command:

```bash
make smoke-live-checkpoint
```

Expected:

- live checkpoint completes
- `metadata.json` says `mock: false`
- `checkpoint.md` uses live wording
- source map includes real source URLs

## Gate 5 — Live full QA

Command:

```bash
./scripts/load_env_and_run.sh .venv/bin/arf run "Research Costco before a supplier meeting" --full --qa --mode brief --lens sales
```

Expected:

- run completes
- `evidence_ledger.json` exists
- `draft_report.md` exists unless evidence blocks synthesis
- `qa_review.json` exists if synthesis occurred
- `report.md` exists only when QA has no high-severity issues

---

# Report publication gate

A final report is publishable only when:

```text
metadata.status == "report_ready"
qa_review.ready_to_publish == true
no high-severity QA issues
report.md exists
draft_report.md exists
evidence_ledger.json exists
source_map.json exists
```

If any of these fail, the correct status is one of:

```text
checkpoint_ready
evidence_needs_review
draft_needs_qa
draft_needs_revision
needs_review
```

---

# Evidence quality gates

## Required

- every fact has `source_id` or `source_url`
- every source ID exists in `source_map.json`
- every high-confidence fact uses a high-authority source
- duplicate claim IDs are deduplicated or blocked
- specialist facts cannot bypass the evidence ledger

## Next additions

- near-duplicate detection across different claim IDs
- evidence usefulness classification
- source-content-backed excerpts
- source freshness check
- source diversity check

---

# QA issue categories to add

Add categories to `QAIssue` when possible:

```text
unsupported_claim
weak_source
missing_recent_signal
overconfident_inference
source_gap
stale_or_unclear_recency
missing_user_context
report_structure_issue
evidence_quality_issue
source_diversity_issue
```

This will make QA results easier to turn into repairs.

---

# Eval fixtures

Create fixtures for:

## 1. Company meeting prep

Request:

```text
Research Costco before a supplier meeting
```

Expected behaviors:

- source map includes primary company sources
- evidence limitations are explicit
- supplier claims are cautious
- final report may be blocked if no strong supplier docs exist

## 2. Investment memo

Request:

```text
Research Nvidia for an investment discussion
```

Expected behaviors:

- filings, investor materials, earnings, competitors
- risks
- recent developments
- no valuation claim without source

## 3. Industry primer

Request:

```text
Research the waste management industry
```

Expected behaviors:

- industry definition
- value chain
- market structure
- major players
- regulation
- public data sources

---

# Golden-run evaluation dimensions

Score each run 1–5:

| Dimension | Question |
|---|---|
| Source relevance | Are sources relevant to the charter? |
| Source authority | Are primary/authoritative sources preferred? |
| Source diversity | Are there enough non-company sources? |
| Evidence depth | Are claims substantive or merely source-descriptive? |
| Traceability | Can every material claim be traced? |
| Recency | Are current claims supported by current sources? |
| Report usefulness | Does the draft help the user's actual decision/meeting? |
| QA usefulness | Are QA issues specific and actionable? |
| Conservatism | Does the report avoid overclaiming? |

A report should not be publishable if any of these are true:

- unsupported material claim
- high-confidence claim from weak source
- missing source appendix
- fabricated source or URL
- missing evidence ledger
- missing QA review
- stale information presented as current
