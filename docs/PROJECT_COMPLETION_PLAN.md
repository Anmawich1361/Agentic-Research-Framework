# Project Completion Plan

This is the authoritative roadmap for finishing Agentic Research Framework as a
V1 CLI-first agentic research system. Keep `README.md` as the product overview,
keep `docs/CURRENT_STATUS.md` as the latest state note, and use this document to
scope future Codex goals and pull requests.

Last updated: 2026-05-27.

## V1 Completion Definition

The project is complete for V1 when the CLI can reliably take a company or
industry research request through the existing artifact-first workflow without
weakening evidence safety:

1. Create a structured research charter and research plan.
2. Discover, score, and checkpoint sources for user review.
3. Continue into deeper research after source approval or feedback.
4. Fetch bounded source content, record source-fetch outcomes, and extract only
   supported evidence claims.
5. Build an evidence ledger where every material report claim maps to a valid
   evidence entry.
6. Generate a cited markdown draft that uses only allowed claim IDs and known
   source IDs.
7. Run deterministic validation and QA before final publication.
8. Write `report.md` only when QA was requested, QA ran, and no high-severity
   QA issues remain.
9. Save all reviewable run artifacts under `runs/<run_id>/` with stable
   filenames and clear status metadata.
10. Provide deterministic mock, eval, regression, and smoke workflows that future
    PRs can run without network or OpenAI API access.

V1 completion does not mean every live source can be fetched or every draft is
automatically publishable. It means source gaps, evidence gaps, traceability
failures, and QA blockers are exposed as explicit run statuses and review
artifacts instead of being hidden behind fluent unsupported prose.

## Explicit Non-Goals

Do not build these for V1 unless the user explicitly changes scope:

- web app
- database
- auth
- background jobs
- scheduler
- vector DB
- PDF/DOCX export
- complex SEC parser

Bounded source fetching, simple filing URL handling, markdown artifacts, and
filesystem-based run storage are in scope. Product surfaces beyond the CLI are
not.

## Current Validated State

PR #17 hardened the live QA and publication path:

- Failed, skipped, and fallback-only source results are blocked from ordinary
  factual synthesis.
- Search-snippet and weak fallback context cannot become material report facts.
- Company reports stop before synthesis when direct company, filing, investor,
  or earnings evidence is missing after filtering.
- Conservative meeting-prep fallback reports are limited to the supplier-meeting
  brief shape and cite only claims they actually use.
- `report.md` remains gated on `--qa`, successful pre-QA validation, QA
  execution, and zero high-severity QA issues.

PR #18 extracted cohesive helper modules from `orchestrator.py` while preserving
artifact names, statuses, mock mode, and publication gates:

- `src/agentic_research/evidence_pipeline.py` owns evidence URL repair,
  failed/skipped/fallback filtering, deduplication, specialist claim merging,
  and direct-company evidence sufficiency checks.
- `src/agentic_research/source_context.py` owns fetched URL updates, SEC
  verification notes, source-content payload shaping, weak fallback context, and
  synthesis source-evidence context.
- `src/agentic_research/conservative_report.py` owns conservative fallback
  report creation, missing-section repair, claim-reference rules, and synthesis
  quality rules.

Current main also includes a deterministic eval and regression harness:

- `make eval` runs fixture-based quality and safety checks for publishable and
  expected-blocking cases.
- `make eval-regression` exercises fake-agent workflow scenarios for
  `run_research` and `continue_research`, including `report.md` publication
  rules and review-artifact presence.
- Tests cover prompt/config loading, source scoring, evidence validation, report
  writing, artifact writing, QA, source context, source ingestion, evals, and
  mock/live-orchestrator behavior without live API calls.

Known remaining risks:

- The live and continue branches still duplicate synthesis, pre-QA validation,
  QA, conservative revision, and status selection flow.
- Source retrieval is still bounded and can fail on primary/company/investor
  pages, SEC access, SSL issues, PDFs, or blocked pages.
- Report quality can still produce non-blocking QA caveats around recency,
  supplier-meeting specificity, and separating verified findings from search
  gaps.
- Operator review is artifact-rich but still requires manual inspection across
  several files.

## Remaining Milestones

### 1. Deterministic Eval and Regression Harness

Goal: make quality, safety, and artifact regressions measurable before changing
live workflow behavior.

Current baseline exists on main. Treat this milestone as complete only when the
harness is stable enough to be the first diagnostic layer for future PRs.

Acceptance criteria:

- `make eval` covers both publishable and expected-blocking fixtures for source
  grounding, evidence depth, unsupported claims, report usefulness, recency,
  source diversity, fallback-only evidence, indirect-only company evidence,
  stale claim IDs, and thin conservative reports.
- `make eval-regression` verifies full-run and continue-run artifact contracts,
  including `metadata.status`, `draft_report.md`, `qa_review.json`,
  `report.md`, `evidence_review.md`, and `report_revision.md`.
- Eval outputs include markdown scorecards and machine-readable failure details.
- Eval fixtures and regression scenarios are deterministic and make no live API
  or network calls.
- Documentation explains how to add a fixture or workflow scenario without
  weakening expected-blocking guardrails.

### 2. Remove Duplicated Live/Continue Synthesis and QA Flow

Goal: reduce orchestration drift by sharing the live `run_research` and
`continue_research` synthesis/QA path.

Acceptance criteria:

- Shared helpers build the synthesis payload, run synthesis, repair missing
  sections, validate traceability/sections, run QA with conservative revision,
  choose final status, and decide whether `report.md` can be written.
- `run_research` and `continue_research` preserve their current public function
  signatures, CLI behavior, metadata fields, and artifact filenames.
- Mock mode remains deterministic and does not call live agents.
- Existing tests for `draft_needs_revision`, `needs_review`,
  `evidence_needs_review`, and `report_ready` still pass without rewriting
  their safety expectations.
- The PR is a mechanical behavior-preserving refactor, not a report-quality or
  retrieval feature PR.

### 3. Improve Source Retrieval Reliability

Goal: make primary/company/SEC/investor retrieval more reliable while keeping
source gaps explicit and avoiding a complex parser.

Acceptance criteria:

- Source discovery prioritizes official company pages, investor materials,
  earnings releases/transcripts, and SEC filing pages when the target is a
  company.
- Per-query search failures remain non-fatal and continue to appear in
  `source_map.gaps` or source-fetch artifacts.
- Bounded SEC and company-source fallbacks repair stale or indirect filing URLs
  when possible, but do not introduce a complex SEC parser.
- Failed, skipped, and fallback-only fetches remain blocked from factual
  synthesis unless fetched source text is available.
- Tests use static search/fetch fakes and do not require network access.
- Live source gaps produce clear `evidence_review.md`, `artifact_review.md`, or
  `source_fetch_log.json` signals instead of crashing or publishing weak prose.

### 4. Improve Report Quality and Reduce Non-Blocking QA Caveats

Goal: make publishable reports more useful while preserving strict gates.

Acceptance criteria:

- Synthesis instructions and deterministic checks keep verified facts,
  cautious inferences, and open questions visibly separate.
- Supplier-meeting recommendations cite direct claim IDs or are framed as
  questions/hypotheses to confirm.
- Recency language is tied to explicit source dates or caveated as unverified.
- Conservative fallback output remains narrow, source-grounded, and limited to
  eligible meeting-prep reports.
- QA high-severity blocking is not weakened; non-blocking medium/low caveats are
  reduced through better evidence use and clearer report structure.
- At least one deterministic eval fixture or regression scenario is added or
  tightened for each new report-quality behavior.

### 5. Improve Artifact Review and Operator UX

Goal: make it faster for a CLI operator or future Codex run to understand what
happened without opening every artifact manually.

Acceptance criteria:

- `review-run`, `show`, or related CLI output summarizes run status, final
  publication state, blocking warnings, QA severity counts, source-fetch
  counts, missing artifacts, and next actions.
- Review artifacts distinguish source access failures, evidence validation
  blockers, pre-QA traceability failures, QA blockers, and successful final
  publication.
- Artifact review improvements preserve existing artifact filenames and do not
  move run storage out of `runs/<run_id>/`.
- Tests cover the new summary behavior with deterministic run directories.
- No database, web UI, background worker, scheduler, or document export is
  introduced.

### 6. Documentation and Release-Readiness Pass

Goal: make V1 understandable and safe for future contributors and Codex goals.

Acceptance criteria:

- `README.md` remains a concise overview and links to this roadmap, current
  status, local development, artifact contract, and run status docs.
- `docs/CURRENT_STATUS.md` is updated after every milestone with the current
  validation bundle, latest meaningful live-run status when applicable, and
  remaining risks.
- Planning/archive docs are clearly marked as historical when they no longer
  describe current behavior.
- CLI commands, artifact filenames, statuses, validation commands, and non-goals
  are consistent across docs.
- A release-readiness checklist records the final V1 validation results and any
  accepted limitations.

## Required Validation Commands

Run these before opening a milestone PR:

```bash
make doctor
make check
make eval
make smoke-mock
git diff --check
```

For refactors or quality changes that touch workflow safety, also run:

```bash
make eval-regression
```

## Optional Live Validation

Run this only when live validation is useful and the local `.env` has
`OPENAI_API_KEY` configured:

```bash
./scripts/load_env_and_run.sh .venv/bin/arf run "Research Costco before a supplier meeting" --full --qa --mode brief --lens sales
```

After a live run, inspect `runs/<run_id>/metadata.json`, `source_fetch_log.json`,
`evidence_review.md`, `draft_report.md`, `qa_review.json`, `report_revision.md`,
`artifact_review.md`, and `report.md` as applicable before claiming the run is
publishable.

## Rules for Future Codex PRs

- Ship one milestone or one coherent slice of a milestone per PR.
- Preserve `--mock` mode.
- Do not make live API calls in tests.
- Preserve artifact filenames.
- Preserve evidence validation, report traceability, fallback-only evidence
  blocking, QA high-severity blocking, and `report.md` publication gates.
- Update `docs/CURRENT_STATUS.md` after each milestone.
- Keep changes CLI/filesystem-first unless the user explicitly changes scope.
- Stage only intended files; do not include `.env`, `.venv`, `runs/`, caches, or
  generated demo artifacts in milestone PRs.

## Stop Rules

- Do not attempt all milestones in one PR.
- Do not merge the PR.
- Stop and document any blocker if validation fails.
- Stop and document any blocker if the scope becomes unclear.
- Stop rather than weakening safety gates to make a report publish.
- Stop rather than adding a V1 non-goal to work around a CLI or artifact issue.
