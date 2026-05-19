# Codex Phase Prompts

Use these one phase at a time. Do not paste all phases at once.

---

## Phase 2 Prompt — Agents SDK integration

```text
Implement Phase 2: OpenAI Agents SDK integration.

Read:
- IMPLEMENTATION_PHASES.md
- ARCHITECTURE.md
- prompts/agents/*.md
- schemas/*.json

Requirements:
1. Add OpenAI Agents SDK support while preserving `--mock` mode.
2. Implement an agent factory in `src/agentic_research/agents.py`.
3. Create agents:
   - Intake Agent
   - Research Planner Agent
   - Source Discovery Agent
   - Synthesis Agent
   - QA Agent
4. Load agent instructions from `prompts/agents/*.md`.
5. Use structured Pydantic outputs where possible.
6. Add live checkpoint mode:

   arf run "Research Costco before a supplier meeting" --checkpoint-only

7. Live checkpoint mode should:
   - run intake
   - run planning
   - run source discovery
   - score sources deterministically
   - write checkpoint artifacts
8. Do not implement final long reports yet.
9. Do not implement specialist agents yet.
10. Tests must mock agent outputs and avoid live API calls.
11. All tests must pass.
```

---

## Phase 3 Prompt — Source discovery tools

```text
Implement Phase 3: source discovery tooling.

Requirements:
1. Add a source discovery tool layer under `src/agentic_research/tools/`.
2. Add a web search wrapper compatible with the agent layer.
3. The Source Discovery Agent should produce structured source candidates.
4. Every source candidate must include:
   - title
   - publisher
   - url
   - source_type
   - publication_date, if available
   - relevance_rationale
   - recommended_uses
   - bias_risk
5. Save raw source candidates to `runs/<run_id>/sources.json`.
6. Save scored and filtered sources to `runs/<run_id>/source_map.json`.
7. Add deterministic tests using mocked search responses.
8. Do not scrape large documents yet.
9. All tests must pass.
```

---

## Phase 4 Prompt — Evidence ledger workflow

```text
Implement Phase 4: evidence ledger workflow.

Requirements:
1. Add a deep research mode:

   arf run "Research ServiceTitan before a sales meeting" --full

2. After source discovery, extract evidence claims from approved or high-scoring sources.
3. EvidenceClaim must include:
   - claim
   - claim_type: fact | inference | opinion | unknown
   - source_id
   - source_title
   - source_url
   - source_type
   - confidence: high | medium | low
   - report_section
   - quote_or_excerpt optional
4. Save evidence to `runs/<run_id>/evidence_ledger.json`.
5. Add validation:
   - every fact claim must have a source_url or source_id
   - every high-confidence claim must come from an authority score >= 4 source when score data is available
   - report generation should warn or fail if unsupported claims exist
6. Add tests for validation.
7. All tests must pass.
```

---

## Phase 5 Prompt — Final report generation

```text
Implement Phase 5: final report generation.

Requirements:
1. Use report templates from `templates/`.
2. Add report generation using the Synthesis Agent.
3. The Synthesis Agent must receive:
   - research charter
   - research plan
   - source map
   - evidence ledger
   - selected report template
4. Save draft report to `runs/<run_id>/draft_report.md`.
5. If QA is not requested, save the same content or a cleaned version to `runs/<run_id>/report.md`.
6. The report must include:
   - executive summary
   - key findings
   - business or industry overview
   - competitors when relevant
   - risks
   - open questions
   - source appendix
7. Source references must come from the evidence ledger or source map.
8. Add tests using mocked synthesis output.
9. All tests must pass.
```

---

## Phase 6 Prompt — QA review

```text
Implement Phase 6: QA and red-team review.

Requirements:
1. Add QA mode:

   arf run "Research Salesforce for an investment memo" --full --qa

2. The QA Agent should review:
   - research charter
   - source map
   - evidence ledger
   - draft report
3. QAReview must include:
   - ready_to_publish: boolean
   - issues
   - severity
   - suggested_fix
4. Add deterministic QA checks in code:
   - no source appendix warning
   - no risks section warning
   - no open questions warning
   - unsupported fact claim warning
   - high-confidence claim from low-authority source warning
5. Save QA output to `runs/<run_id>/qa_review.json`.
6. If high-severity issues exist, mark run status as `needs_review` and do not overwrite report.md as final.
7. Add tests.
8. All tests must pass.
```

---

## Phase 7 Prompt — Specialist agents

```text
Implement Phase 7: specialist agents.

Requirements:
1. Add specialist agents:
   - Industry Agent
   - Competitor Agent
   - News Agent
   - Risk Agent
   - Financial Agent
   - Filings Agent
2. Load their prompts from `prompts/agents/`.
3. The orchestrator should select specialists based on research lens:
   - sales: company, news, competitor, risk-lite
   - investment: financial, industry, competitor, risk, filings when public
   - interview: company, history, news, strategy
   - industry: industry, competitor, news, risk
   - diligence: filings, financial, industry, competitor, risk, news
4. Specialist outputs must become evidence claims or structured analysis objects.
5. Do not allow uncited specialist facts into the final report.
6. Add mocked tests for specialist selection.
7. All tests must pass.
```


# Phase 9 Prompt — Evidence and Artifact Quality Hardening

```text
Implement Phase 9: evidence and artifact quality hardening.

Current state:
- Live checkpoint works.
- Live --full --qa reaches draft_report.md and qa_review.json.
- Final report is correctly blocked when QA finds high-severity issues.
- Evidence duplicate claim IDs are now handled.
- The latest live run still shows artifact-quality issues: evidence can be shallow, report claims can be generic, and QA blocks publication.

Do not add UI features.
Do not add a database.
Do not change final-report gating.
Do not commit .env, .venv, runs/, or generated artifacts.

Goals:
1. Improve evidence quality before synthesis.
2. Reduce duplicated and near-duplicated evidence claims.
3. Make synthesis more conservative and evidence-bound.
4. Make QA issues more actionable and categorized.
5. Add a live artifact review summary.

Required work:

A. Evidence quality module
- Add src/agentic_research/evidence_quality.py.
- Add normalized claim text comparison.
- Detect near-duplicate evidence claims even when IDs differ.
- Detect claims that are only "source describes itself" rather than substantive evidence.
- Classify evidence claims as:
  - substantive
  - source_metadata_only
  - source_finding_aid
  - weak_inference
  - unsupported_or_unclear
- Add tests for c1/r1-style near duplicates.

B. Artifact review module
- Add src/agentic_research/artifact_review.py.
- Given a run directory, produce a markdown artifact review:
  - status
  - files present/missing
  - evidence claim count
  - unique claim ID count
  - near-duplicate count
  - QA high/medium/low issue counts
  - final report published: yes/no
  - next recommended action
- Add optional CLI command:
  arf review-run <run_id>
  or a script:
  python -m agentic_research.artifact_review runs/<run_id>
- Save review as:
  runs/<run_id>/artifact_review.md
  when run after a full workflow, if easy.

C. Synthesis prompt tightening
- Update prompts/agents/synthesis_agent.md.
- Require broad strategy/supplier claims to be framed as inference unless directly supported.
- Require the report to distinguish:
  - directly supported facts
  - cautious inferences
  - open questions
- For recent developments, require concrete source evidence or explicitly state that recent signals could not be verified.
- For supplier-meeting claims, require direct source support or explicit caveat.

D. QA improvements
- Update QA model or issue handling to include an optional issue category if easy:
  - unsupported_claim
  - weak_source
  - missing_recent_signal
  - overconfident_inference
  - source_gap
  - stale_or_unclear_recency
  - missing_user_context
  - report_structure_issue
- Keep high-severity QA issues blocking final report.
- Add tests showing unsupported broad claims are flagged.

E. Live smoke documentation
- Add docs/live-smoke/phase-8-full-qa-smoke.md.
- Summarize:
  - run ID
  - status
  - artifacts produced
  - QA blockers
  - evidence-quality issues
  - recommended next fixes

Validation:
- make reset-env
- make doctor
- make check
- make smoke-mock
- ./scripts/load_env_and_run.sh .venv/bin/arf run "Research Costco before a supplier meeting" --full --qa --mode brief --lens sales

Return:
- changed files
- commands run
- whether report.md was written or blocked
- artifact review summary
- remaining issues
```

---

# Phase 10 Prompt — Source Content Ingestion

```text
Implement Phase 10: source content ingestion.

Current issue:
The framework discovers source URLs but does not reliably fetch and parse source content. Evidence extraction is therefore too dependent on search snippets and source metadata.

Goal:
Add a source content ingestion layer so evidence claims are extracted from actual source text.

Do not add UI features.
Do not add a database.
Do not commit .env, .venv, runs/, or generated artifacts.

Requirements:

A. Source content models
- Add models for:
  - SourceFetchResult
  - SourceContent
  - SourceChunk
  - SourceFetchLog
- Include:
  - source_id
  - url
  - status: fetched | failed | skipped
  - content_type
  - title
  - text
  - excerpt/chunks
  - error message if failed

B. HTML fetching
- Add src/agentic_research/source_ingestion.py.
- Fetch only included/high-scoring sources by default.
- Parse HTML into readable text.
- Remove scripts/nav/footer noise where feasible.
- Respect timeouts.
- Do not fail the run if one source fetch fails.

C. PDF handling
- Add conservative PDF handling if simple dependencies are available.
- If not implemented, log PDFs as skipped with reason.

D. Artifact output
- Save:
  runs/<run_id>/source_content.json
  runs/<run_id>/source_fetch_log.json

E. Evidence extraction integration
- Pass source_content/chunks into the evidence extraction agent.
- Instruct evidence extraction to cite short excerpts from actual content.
- Prefer source content over search snippets.

F. Tests
- Mock HTML fetches.
- Test failed fetches are logged.
- Test evidence payload includes source content.
- Test no live internet/API calls in tests.

Validation:
- make check
- make smoke-mock
- live --full --qa on Costco

Acceptance:
- evidence ledger quote_or_excerpt should come from fetched content when available.
- source fetch failures should not crash the run.
```

---

# Phase 11 Prompt — Report Quality and Template Discipline

```text
Implement Phase 11: report quality and template discipline.

Goal:
Make draft reports more useful, less generic, and more aligned to the research lens.

Do not add UI features.
Do not add a database.
Do not remove QA gating.

Requirements:

A. Report validation module
- Add src/agentic_research/report_validation.py.
- Move report section validation out of orchestrator.
- Validate:
  - required headings
  - claim ID references
  - source references
  - unsupported broad language markers
  - missing caveats when evidence is thin

B. Template-specific section requirements
- Meeting prep brief:
  - Executive Summary
  - Context for Meeting
  - What We Know
  - What We Do Not Know
  - Supplier/Buyer Angle
  - Questions to Ask
  - Risks and Watchouts
  - Source Appendix
- Company brief:
  - Executive Summary
  - Business Overview
  - Market Context
  - Competitive Landscape
  - Recent Developments
  - Risks
  - Open Questions
  - Source Appendix
- Industry primer:
  - Executive Summary
  - Industry Definition
  - Value Chain
  - Key Players
  - Demand Drivers
  - Risks
  - Open Questions
  - Source Appendix

C. Prompt updates
- Update synthesis prompt to follow the selected template exactly.
- Require an explicit "Evidence Limitations" section when the source set is thin.
- Require "What We Do Not Know" for meeting prep.

D. Tests
- Add tests for template-specific required sections.
- Add tests for thin-evidence caveat.
- Add tests that generic claims without evidence are blocked or downgraded.

Validation:
- make check
- make smoke-mock
- live --full --qa on Costco

Acceptance:
- The draft is still blocked if quality is insufficient.
- When blocked, QA issues should map clearly to missing evidence or overconfident phrasing.
```

---

# Phase 12 Prompt — Evaluation Harness

```text
Implement Phase 12: evaluation harness.

Goal:
Create repeatable quality checks for research output.

Do not depend on live API calls for normal tests.

Requirements:

A. Eval structure
Create:

evals/
  fixtures/
  rubrics/
  run_eval.py
  README.md

B. Fixtures
Add three fixture scenarios:
1. company meeting prep
2. investment memo
3. industry primer

Each fixture should include:
- request
- mock source map
- mock evidence ledger
- expected QA characteristics
- expected report sections

C. Rubrics
Add rubric files for:
- source grounding
- evidence depth
- report usefulness
- unsupported claims
- source diversity
- recency handling

D. Eval runner
The eval runner should:
- load fixtures
- run deterministic checks
- produce a scorecard
- not call live APIs unless explicitly requested

E. Documentation
Add docs/EVALUATION.md.

Validation:
- make check
- python evals/run_eval.py

Acceptance:
- eval runner works locally
- at least three fixtures run
- failures are readable and actionable
```

---

# Phase 13 Prompt — User Checkpoint and Continue Workflow

```text
Implement Phase 13: checkpoint and continue workflow.

Goal:
Make the gated research process usable as intended.

Current issue:
The system can produce checkpoint artifacts and full reports, but it does not yet have a clean way for the user to answer checkpoint questions and continue the same run.

Requirements:

A. CLI commands
Add:
- arf runs
- arf show <run_id>
- arf continue <run_id>
- arf add-feedback <run_id>
- optional: arf approve-sources <run_id>

B. User feedback artifact
Save:
runs/<run_id>/user_feedback.json

It should include:
- answered checkpoint questions
- source approvals/rejections
- depth override
- lens override
- user notes
- priority topics

C. Continue behavior
`arf continue <run_id>` should:
- load existing charter, plan, source_map
- include user feedback in evidence/specialist/synthesis prompts
- avoid rerunning source discovery unless requested
- write new artifacts or a child run

D. Tests
- continue from checkpoint with mock artifacts
- user feedback is included in synthesis payload
- rejected sources are not used

Validation:
- make check
- make smoke-mock

Acceptance:
- The system supports the intended human-in-the-loop checkpoint.
```

---

# Phase 14 Prompt — Production Readiness Foundation

```text
Implement Phase 14: production readiness foundation.

Goal:
Prepare the repo for future hosted use without building a web app.

Requirements:

A. CI
Add GitHub Actions:
.github/workflows/ci.yml

Run:
- make setup or equivalent
- make check
- no live API calls

B. Logging
Add structured local logging:
- run stage start/end
- agent calls
- tool calls
- artifact paths
- errors

C. Run metadata
Extend metadata with:
- started_at
- completed_at
- duration_seconds
- model
- run_type
- status
- status_reason

D. Failure handling
Ensure all major failures write:
- metadata.json
- failure_report.md or error.json
- no partial final report

E. Documentation
Add docs/PRODUCTION_READINESS.md.

Validation:
- make check
- CI passes

Acceptance:
- GitHub Actions pass
- failures are inspectable
- future UI has stable artifact contracts
```
