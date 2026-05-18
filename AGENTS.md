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
