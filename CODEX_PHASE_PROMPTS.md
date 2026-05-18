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
