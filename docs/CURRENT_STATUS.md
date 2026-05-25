# Current Status

This note records the stabilization point after PR #5 and PR #6.

## Recent Merges

PR #5 implemented phases 9-14 in one large merge. It added or hardened the
quality-focused parts of the pipeline: evidence quality review, source ingestion,
artifact review, report validation, QA structure, and production-readiness docs.

PR #6 fixed stale claim-reference integrity. Synthesis now receives
`allowed_claim_ids` from the final evidence ledger after deduplication,
evidence-quality filtering, specialist merge, and claim-ID renaming. Pre-QA
validation now catches unknown claim references before QA and writes a clear
draft-revision diagnostic.

Both merges are kept. This stabilization pass focuses on documentation and
artifact contracts before adding more research features.

## Current Blocker

The current blocker is content quality, not claim-ID integrity.

The current system can complete live full QA runs. Those runs can reach
synthesis and QA without unknown evidence claim references. QA can still block
publication when the report overstates evidence, lacks recent Costco-specific
support, or presents inferred supplier priorities too confidently.

The next work should be quality refinement, not new features. Priority areas
include stronger evidence, better source grounding, more conservative synthesis,
and smaller/refactored orchestration modules.

## 2026-05-25 Production-Readiness Update

This pass narrowed the live full-QA path instead of weakening gates:

- Evidence claims tied to failed or skipped source fetches are dropped before
  synthesis.
- Retrieval-gap pseudo-claims, such as fetched pages returning no usable filing
  data, are no longer treated as substantive evidence.
- Company reports now stop before synthesis when no direct company, filing,
  investor, or earnings evidence claims remain after filtering.
- If QA blocks an overconfident draft, the pipeline tries a conservative
  source-grounded fallback report that cites only claims it actually uses and
  excludes current/recent/strategy claims and secondary industry-primer claims.
- Per-query web-search failures no longer abort the whole source-discovery
  stage.

Validation run before this handoff:

- `make doctor`
- `make check`
- `make smoke-mock`
- live Costco full-QA command:
  `./scripts/load_env_and_run.sh .venv/bin/arf run "Research Costco before a supplier meeting" --full --qa --mode brief --lens sales`

Latest inspected live run: `run_20260525T152401Z_7f40415a`.

That run correctly blocked at `evidence_needs_review`, before synthesis and QA,
because no source content was fetched. `source_fetch_log.json` shows six direct
Costco investor/filing/earnings sources failed with HTTP 403, no readable text,
or an SSL timeout. No `draft_report.md`, `qa_review.json`, or `report.md` was
written, which preserves the publication gate for a legitimate external source
access gap.

Remaining risk: live source coverage still depends on external search and
fetchability. A future improvement should add a more reliable primary-source
retrieval path for SEC/company filings without turning this into a complex SEC
parser.

## 2026-05-25 PR #17 Follow-Up Update

This follow-up rebased the PR branch onto `origin/main` and tightened the
conservative live-QA path without changing publication gates:

- The conservative report fallback now uses `charter.target` instead of
  hard-coded Costco wording.
- The supplier-meeting fallback is limited to meeting-prep deliverables instead
  of being applied to unrelated report templates.
- Direct evidence sufficiency now accepts fetched primary/company, filing,
  investor, earnings-release, and earnings-transcript facts even when the claim
  text includes current/latest/earnings/strategy wording. The stricter
  current/recent wording filter remains only for conservative fallback claim
  selection.
- Failed/skipped source filtering now drops claims by either `source_id` or a
  matching `source_url`, including URL-only claims.
- `search_many` still tolerates per-query failures, but failed query diagnostics
  are recorded and surfaced in `source_map.gaps`.
- Fetched SEC archive filings clear stale source-map warnings that claimed a
  retrieved SEC filing was only a future-dated/unverified candidate.

Validation after this follow-up:

- `make doctor`
- `make check`
- `make smoke-mock`
- live Costco full-QA command:
  `./scripts/load_env_and_run.sh .venv/bin/arf run "Research Costco before a supplier meeting" --full --qa --mode brief --lens sales`

Latest inspected live run: `run_20260525T173247Z_149e704f`.

That run completed with `metadata.status = report_ready`, wrote `report.md`,
and `qa_review.json` had zero high-severity issues. QA still recorded medium and
low caveats around missing category/counterpart context, uneven recency, and
explicitly caveating supplier-meeting inferences. Those are remaining quality
risks, not publication blockers.

## Publication Gate

Final report publication remains QA-gated.

The framework writes `report.md` only when:

- the workflow is run with `--qa`,
- deterministic pre-QA report validation passes,
- QA runs,
- no high-severity QA issues remain.

Blocked runs retain review artifacts such as `draft_report.md`,
`qa_review.json`, `report_revision.md`, `evidence_review.md`, or
`artifact_review.md` as applicable.

## 2026-05-25 Orchestrator Helper Extraction

This pass reduced `src/agentic_research/orchestrator.py` from about 2,800 lines
to about 1,600 lines by moving cohesive helper logic into focused modules:

- `src/agentic_research/evidence_pipeline.py` now owns evidence claim URL
  repair, failed/skipped/fallback source filtering, evidence sanitization,
  deduplication, specialist claim merging, and direct-company evidence
  sufficiency checks.
- `src/agentic_research/source_context.py` now owns fetched source-map URL
  updates, SEC fetch-verification notes, source-content payload shaping,
  weak search-snippet fallback contexts, source-fetch-log fallback transforms,
  and synthesis source-evidence context.
- `src/agentic_research/conservative_report.py` now owns conservative
  meeting-prep fallback report creation, conservative claim selection,
  source appendix/evidence limitations, supplier-meeting fallback eligibility,
  and missing-section repair helpers.

Validation run for this refactor:

- `make doctor`
- `make check`
- `make smoke-mock`
- `git diff --check`
- live Costco full-QA command:
  `./scripts/load_env_and_run.sh .venv/bin/arf run "Research Costco before a supplier meeting" --full --qa --mode brief --lens sales`

Latest inspected live run: `run_20260525T184647Z_504e0610`.

That run completed with `metadata.status = report_ready`, wrote `report.md`,
and `qa_review.json` had zero high-severity issues. QA still recorded three
medium issues and one low issue around recency framing, generic supplier-meeting
recommendations, and separating verified findings from search gaps.

Remaining risk: orchestration is smaller but still coordinates long live and
continue branches with duplicated synthesis/QA flow. Future refactors should
continue extracting workflow-stage builders only after preserving the current
artifact names, mock mode, evidence gates, and final-report publication rules.
