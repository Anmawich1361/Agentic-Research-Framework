# Next Codex Prompt — Phase 9

Paste this into Codex after syncing `main`.

```text
Implement Phase 9: evidence and artifact quality hardening.

Current project state:
- The CLI workflow works.
- Local development is hardened through Makefile targets.
- Live checkpoint runs work.
- Live --full --qa can produce draft_report.md and qa_review.json.
- Final report gating works: report.md is not written when QA has high-severity issues.
- Duplicate evidence claim ID handling has been added.
- The latest live Costco supplier-meeting run still produced a draft that QA blocked because it made broad supplier-priority claims without enough direct support.

Do not add UI features.
Do not add a database.
Do not change final-report gating.
Do not commit .env, .venv, runs/, or generated artifacts.

Goal:
Improve artifact quality so the system produces stronger evidence ledgers, more conservative drafts, and more actionable QA reviews.

Required work:

1. Add src/agentic_research/evidence_quality.py
   - Detect near-duplicate claims where IDs differ but normalized claim text/source are substantially similar.
   - Detect source-metadata-only evidence claims.
   - Classify claims into:
     - substantive
     - source_metadata_only
     - source_finding_aid
     - weak_inference
     - unsupported_or_unclear
   - Add tests.

2. Integrate evidence quality warnings
   - Add non-blocking evidence quality warnings for near duplicates and low-value claims.
   - Do not block synthesis for all low-value claims, but expose them in artifact review and QA context.
   - Keep blocking behavior for unsupported facts, unknown sources, and conflicting base duplicate IDs.

3. Add src/agentic_research/artifact_review.py
   - Given a run directory, summarize:
     - run status
     - files present/missing
     - evidence claim count
     - unique claim ID count
     - near-duplicate count
     - QA issue counts by severity
     - report.md published yes/no
     - recommended next action
   - Add optional CLI command if simple:
     arf review-run <run_id>
   - Add tests.

4. Tighten synthesis prompt
   - Update prompts/agents/synthesis_agent.md.
   - Require unsupported broad strategy/supplier claims to be omitted or labeled as inference.
   - Require recent developments to include concrete evidence or state that recent signals could not be verified.
   - Require supplier-meeting guidance to say when category-specific evidence is missing.
   - Require "Evidence Limitations" when source set is thin.

5. Improve QA issue structure
   - Add optional category to QAIssue if feasible.
   - Suggested categories:
     - unsupported_claim
     - weak_source
     - missing_recent_signal
     - overconfident_inference
     - source_gap
     - stale_or_unclear_recency
     - missing_user_context
     - report_structure_issue
     - evidence_quality_issue
   - Update tests.

6. Add docs/live-smoke/phase-8-full-qa-smoke.md
   - Summarize the live Costco full QA smoke result:
     - run reached draft_report.md and qa_review.json
     - final report was blocked
     - QA blockers were legitimate
     - next phase is evidence/report quality

Validation:
- make reset-env
- make doctor
- make check
- make smoke-mock
- ./scripts/load_env_and_run.sh .venv/bin/arf run "Research Costco before a supplier meeting" --full --qa --mode brief --lens sales

Return:
- changed files
- validation commands run
- whether report.md was written or blocked
- artifact review summary
- remaining issues
```
