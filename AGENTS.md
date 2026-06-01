# AGENTS.md

## Project

This repository is a Python CLI-first agentic research framework for company and industry research.

The system should:

1. Understand a user research request.
2. Create a research charter.
3. Discover and score sources.
4. Pause at a user checkpoint.
5. Run deeper research after approval.
6. Build an evidence ledger.
7. Generate a cited markdown report.
8. Run QA/red-team checks before final output.

## Coding rules for Codex

- Do not implement the whole system in one giant file.
- Keep orchestration in Python code, not only inside prompts.
- Use Pydantic models for structured data.
- Keep tests deterministic.
- Do not make live OpenAI API calls in tests.
- Preserve `--mock` mode throughout the project.
- Save run artifacts under `runs/<run_id>/`.
- Every material factual claim in a report must map to an evidence ledger entry.
- Prefer small, reviewable changes.
- Do not silently remove files or prompts unless explicitly asked.
- Use type hints where practical.
- Avoid over-engineering early phases.

## Long-running Codex goals

Long-running Codex work is allowed when the user explicitly starts a goal,
asks to finish a roadmap milestone, asks to keep working until validation
passes, or otherwise grants a broad execution scope.

- Treat an explicit goal as permission to continue across multiple
  implementation, debugging, documentation, and validation loops until the
  stated outcome is complete or genuinely blocked.
- Do not stop merely because the task spans many files, takes a long time, or
  requires several verification passes.
- "Prefer small, reviewable changes" means keep each change coherent and easy
  to inspect; it is not a reason to stop before the requested goal is complete.
- Product checkpoint rules apply to ARF research runs, not to Codex's own
  development workflow. If the user asks Codex to implement or validate work,
  continue without asking for intermediate approval unless scope, safety,
  credentials, or destructive operations require it.
- For long goals, leave clear progress notes in the conversation and preserve
  durable evidence in repo artifacts or docs when the task calls for it.
- Stop only for a true blocker: missing credentials, unavailable services,
  unclear or conflicting scope that cannot be resolved from repo context,
  approval needed for destructive or privileged operations, or exhausted user
  budget.
- Do not add product background jobs, scheduled automations, databases, or other
  excluded features just to support a long Codex session.

## Setup commands

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Test commands

```bash
pytest
ruff check .
mypy src
```

## CLI target

```bash
arf run "Research Nvidia before an investor meeting" --mock --checkpoint-only
```

## Architecture sequence

1. Intake
2. Research charter
3. Source discovery
4. Source scoring
5. User checkpoint
6. Deep research
7. Evidence ledger
8. Synthesis
9. QA review
10. Final report

## Do not build yet

Unless specifically requested, do not build:

- web app
- database
- authentication
- background jobs
- scheduled automations
- PDF or DOCX export
- vector database
- complex SEC parser

## File conventions

- Agent prompts live in `prompts/agents/`.
- Research policies live in `prompts/policies/`.
- Workflow prompts live in `prompts/workflows/`.
- JSON schemas live in `schemas/`.
- YAML configuration lives in `configs/`.
- Report templates live in `templates/`.
- Saved run artifacts live in `runs/<run_id>/`.

## Testing expectations

Tests should cover:

- prompt loading
- config loading
- schema validation
- source scoring
- evidence ledger validation
- report writing
- mock orchestrator behavior

No test should require network access or an OpenAI API key.
