# Technical Debt Register

## Highest priority

### 1. Source content is not ingested deeply enough

Current issue:
The system discovers source URLs and uses search/snippet metadata, but it does not reliably fetch, parse, and chunk source documents.

Impact:
Evidence claims are often shallow or source-descriptive.

Next step:
Phase 10 source content ingestion.

---

### 2. Evidence claims can be low-value

Current issue:
Claims often say a source exists rather than extracting a useful business fact.

Examples:
- "Investor relations site is a primary hub..."
- "Vendor inquiries page exists..."

Impact:
Report synthesis has too little substantive evidence.

Next step:
Evidence quality classification and source-content extraction.

---

### 3. Orchestrator is too large

Current issue:
`orchestrator.py` mixes pipeline control, artifact writing, prompt payload assembly, validation, deduplication, report repair, QA, and mock behavior.

Impact:
Future changes will become brittle.

Suggested split:

```text
pipeline.py
artifact_writer.py
evidence_pipeline.py
report_pipeline.py
qa_pipeline.py
run_state.py
```

Priority:
Medium-high after Phase 9.

---

### 4. QA is useful but not structured enough

Current issue:
QA identifies blockers, but issue categories are not systematic.

Impact:
Harder to automate repairs or measure quality.

Next step:
Add QA issue categories and deterministic checks.

---

### 5. Report validation is still partly substring-based

Current issue:
Some validation checks use string inclusion rather than heading parsing.

Impact:
False positives/negatives possible.

Next step:
Markdown heading parser or section extraction helper.

---

## Medium priority

### 6. No CI

Add GitHub Actions for:

```text
make setup
make check
```

No live API calls in CI.

---

### 7. No run continuation

Current issue:
The checkpoint questions are useful, but there is no clean `continue` workflow.

Next step:
Add `arf continue <run_id>` and `user_feedback.json`.

---

### 8. Source taxonomy and required-source normalization need refinement

Current issue:
Natural-language source needs are normalized, but the alias system is still heuristic.

Next step:
Move canonical source need mapping into config.

---

### 9. Prompt files may lag behind implemented behavior

Current issue:
Code has evolved quickly through PRs; prompts and docs may not fully reflect current gates.

Next step:
Prompt/docs alignment sweep.

---

### 10. No cost/latency instrumentation

Current issue:
Live runs can call multiple agents, but no per-stage timing/cost metrics are stored.

Next step:
Add run timing metadata and stage logs.

---

## Low priority

### 11. Exports

PDF/DOCX export is not needed yet. Markdown artifacts are sufficient.

### 12. Web UI

Not needed until the CLI workflow is stable and artifacts are consistently useful.

### 13. Database

Not needed until run continuation, search history, and project persistence require it.
