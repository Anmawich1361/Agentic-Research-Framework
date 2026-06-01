# Current Status

This note records successive stabilization points for the CLI-first framework.

## 2026-06-01 Long-Running Goal Documentation Pass

The V1 roadmap milestones remain complete. This pass fixed the repo guidance
that previously implied Codex should stop at one milestone or one PR-sized
slice even when the user explicitly starts a broader goal.

Validation for this pass:

- `make reset-env`: rebuilt a damaged local `.venv`.
- `make doctor`: passed.
- `make check`: passed with 156 tests; Ruff passed; mypy passed.
- `make eval`: passed with 10/10 fixtures.
- `make eval-regression`: passed with 5/5 workflow scenarios.
- `make smoke-mock`: passed and wrote
  `runs/run_20260601T142504Z_0d3e5333` with `metadata.status =
  checkpoint_ready`.
- `git diff --check`: passed.

## 2026-05-28 V1 Completion Pass

The V1 roadmap milestones in `docs/PROJECT_COMPLETION_PLAN.md` are complete in
the current branch:

- The deterministic eval layer remains the first diagnostic layer and now
  includes 10 quality fixtures, including an unclear-recency fixture that
  requires dated evidence or an explicit caveat.
- Live `run_research` and `continue_research` share the post-evidence
  synthesis, traceability validation, QA, conservative revision, status, and
  publication decision path.
- Company source discovery now adds first-class official company, investor
  relations, earnings release/transcript, and SEC filing queries before
  required-source-type queries.
- Source ingestion can use bounded SEC and company-source fallback resolvers
  while keeping failed, skipped, and fallback-only fetches explicit in
  `source_fetch_log.json` and out of factual synthesis.
- Report validation flags uncaveated current/recent claims when their direct
  evidence source lacks a visible publication date, without weakening
  high-severity evidence and publication gates.
- `arf review-run <run_id>` still writes `artifact_review.md` and now prints a
  compact operator summary with status, publication state, QA severity counts,
  source-fetch counts, blocking warnings, and next action.
- `docs/RELEASE_READINESS.md` records the V1 checklist, validation commands,
  and accepted limitations.

Final validation for this pass:

- `make doctor`: passed.
- `make check`: passed with 156 tests; Ruff passed; mypy passed.
- `make eval`: passed with 10/10 fixtures.
- `make eval-regression`: passed with 5/5 workflow scenarios.
- `make smoke-mock`: passed and wrote
  `runs/run_20260528T182848Z_a2921029` with `metadata.status =
  checkpoint_ready`.
- `git diff --check`: passed.

## 2026-05-27 Project Completion Roadmap

`docs/PROJECT_COMPLETION_PLAN.md` is now the authoritative V1 completion
roadmap. It defines the CLI-first completion bar, hard non-goals, current
validated state after the live-QA gating and helper-extraction work, remaining
milestones, acceptance criteria, required validation commands, future Codex PR
rules, and stop rules.

Future milestone PRs should use that plan for scope control, preserve the
existing evidence/report/QA publication gates, and update this status document
after each completed milestone.

## 2026-05-27 Shared Synthesis/QA Flow Milestone

The live full-run and continue-run branches now share their post-evidence
synthesis and QA path:

- `_build_synthesis_payload` constructs the synthesis prompt payload for both
  `run_research` and `continue_research`; continuation feedback is added only
  for continued runs.
- `_run_synthesis_and_qa` owns synthesis execution, missing-section repair,
  traceability and section validation, report-revision artifact writing,
  QA with conservative revision, final status selection, and `report.md`
  publication eligibility.
- Public function signatures, CLI behavior, mock mode, artifact filenames,
  evidence gates, QA high-severity blocking, and final-report publication gates
  remain unchanged.

Validation for this milestone:

- `make doctor`: ok after repairing the local `.venv`.
- `make check`: 154 tests passed; Ruff passed; mypy passed.
- `make eval`: 9/9 fixtures passed.
- `make eval-regression`: 5/5 workflow scenarios passed.
- `make smoke-mock`: wrote a deterministic checkpoint run.
- `git diff --check`: ok.

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

## 2026-05-26 Evaluation Harness Milestone

The deterministic eval system now covers quality and workflow-safety
regressions instead of only publishable happy paths:

- `make eval` runs publishable and expected-blocking fixtures for source
  grounding, fallback-only evidence, indirect-only company evidence, stale claim
  IDs, and thin conservative meeting-prep reports.
- `make eval-regression` runs fake-agent `run_research` and
  `continue_research` scenarios to verify `metadata.status`, `report.md`
  publication rules, `evidence_review.md`, `report_revision.md`, and fallback
  evidence blocking.
- Both eval runners produce markdown scorecards and optional JSON results for
  CI/Codex review.

This milestone is intended to make evidence safety, traceability, artifact
contracts, and publication gates measurable before future quality changes.

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
