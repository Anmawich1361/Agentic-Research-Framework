# Historical Codex Kickoff Prompt

This archived prompt predates the current V1 implementation and should not be
treated as current behavior.

Paste this into Codex from the root of the repository.

```text
You are implementing Phase 1 of the Agentic Research Framework.

Read these files first:
- README.md
- PROJECT_PLAN.md
- ARCHITECTURE.md
- IMPLEMENTATION_PHASES.md
- AGENTS.md

Goal:
Create a Python CLI-first project with a deterministic mock workflow. Do not make live OpenAI API calls yet.

Implementation requirements:

1. Use a `src/` layout package named `agentic_research`.

2. Create or complete these Python modules:
   - src/agentic_research/__init__.py
   - src/agentic_research/cli.py
   - src/agentic_research/settings.py
   - src/agentic_research/prompts.py
   - src/agentic_research/models.py
   - src/agentic_research/source_scoring.py
   - src/agentic_research/evidence_ledger.py
   - src/agentic_research/report_writer.py
   - src/agentic_research/orchestrator.py
   - src/agentic_research/agents.py
   - src/agentic_research/tools/__init__.py

3. Use Typer for the CLI.

4. Add a CLI command:

   arf run "Research Nvidia before an investor meeting" --mock --checkpoint-only

5. The mock run should:
   - create a unique research run id
   - create `runs/<run_id>/metadata.json`
   - create `runs/<run_id>/charter.json`
   - create `runs/<run_id>/research_plan.json`
   - create `runs/<run_id>/sources.json`
   - create `runs/<run_id>/source_map.json`
   - create `runs/<run_id>/checkpoint.md`
   - print the run id and checkpoint path

6. Add Pydantic models for:
   - ResearchCharter
   - ResearchQuestion
   - ResearchPlan
   - SourceCandidate
   - SourceScore
   - SourceMap
   - EvidenceClaim
   - EvidenceLedger
   - QAReview
   - QAIssue
   - RunMetadata

7. Add deterministic source scoring based on:
   - authority
   - relevance
   - recency
   - bias risk
   - coverage

8. Add an EvidenceLedger class that can:
   - add claims
   - list claims by section
   - validate that fact claims have a source id or URL
   - validate that high-confidence claims do not come from low-authority sources when source score is available

9. Add prompt loading utilities:
   - load_prompt(path_or_name)
   - load_agent_prompt(agent_name)
   - load_policy_prompt(policy_name)

10. Add markdown report/checkpoint writer utilities.

11. Add tests for:
    - prompt loading
    - source scoring
    - evidence ledger validation
    - mock orchestrator run
    - checkpoint artifact creation

12. Do not call the OpenAI API.
13. Do not implement a web UI.
14. Do not add a database.
15. Do not remove any prompt, config, schema, template, or docs files.

Development expectations:
- Keep orchestration in code.
- Keep tests deterministic.
- Use clear file paths and helpful errors.
- Use pathlib.
- All tests must pass with `pytest`.

After implementation:
1. Run `pytest`.
2. Run `arf run "Research Nvidia before an investor meeting" --mock --checkpoint-only`.
3. Show the resulting file tree under `runs/<run_id>/`.
4. Summarize what was implemented and what remains for Phase 2.
```
