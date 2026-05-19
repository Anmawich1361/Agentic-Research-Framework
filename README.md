# Agentic Research Framework

A CLI-first framework for researching companies and industries through a gated, evidence-backed agent workflow.

The goal is not to build a generic chatbot. The goal is to build a repeatable research operating system that can:

1. Understand the user's research purpose.
2. Convert the request into a research charter.
3. Discover and score sources.
4. Pause for user steering before deep work.
5. Extract evidence into a structured ledger.
6. Run specialist analysis.
7. Generate a cited report.
8. Run QA/red-team checks before final delivery.

## Current build target

The first build should be a local Python CLI app, not a web app.

Target command:

```bash
arf run "Research Datadog before an investment discussion" --checkpoint-only
```

Expected output:

```text
runs/<run_id>/
├── metadata.json
├── charter.json
├── research_plan.json
├── sources.json
├── source_map.json
└── checkpoint.md
```

Later full-report command:

```bash
arf run "Research Datadog before an investment discussion" --full --qa
```

Expected output:

```text
runs/<run_id>/
├── metadata.json
├── charter.json
├── research_plan.json
├── sources.json
├── source_map.json
├── evidence_ledger.json
├── draft_report.md
├── qa_review.json
└── report.md
```

## Recommended implementation stack

- Python 3.11+
- OpenAI Agents SDK
- Typer CLI
- Pydantic models
- YAML configs
- Markdown reports
- Local JSON artifacts under `runs/`
- Tests with `pytest`

## Why CLI-first

A CLI-first implementation keeps the first version fast and reviewable. It avoids early complexity from web UI, authentication, database migrations, permissions, hosted workers, and document queues.

The first version should prove the research workflow. A web interface can come later.

## Core workflow

```text
User request
  ↓
Intake and intent detection
  ↓
Research charter
  ↓
Research plan
  ↓
Source discovery
  ↓
Source scoring and filtering
  ↓
User checkpoint
  ↓
Deep research
  ↓
Evidence ledger
  ↓
Specialist analysis
  ↓
Synthesis
  ↓
QA / red-team review
  ↓
Final report
```

## Build phases

### Phase 1 — Deterministic skeleton

Build a working project without live AI calls.

Required:

- CLI entrypoint
- prompt loader
- config loader
- Pydantic models
- source scoring
- evidence ledger class
- markdown writers
- mock orchestrator
- tests

Target command:

```bash
arf run "Research Nvidia before an investor meeting" --mock --checkpoint-only
```

### Phase 2 — Real agent checkpoint workflow

Add OpenAI Agents SDK integration.

Required agents:

- Intake Agent
- Research Planner Agent
- Source Discovery Agent
- Research Manager Agent

Target command:

```bash
arf run "Research Costco before a supplier meeting" --checkpoint-only
```

### Phase 3 — Source discovery tooling

Add web search and source candidate collection.

Required:

- Save raw source candidates
- Classify source types
- Score sources deterministically
- Produce source map
- Preserve all URLs and publication dates where available

### Phase 4 — Evidence ledger

Add evidence extraction and claim tracking.

Required:

- Every material fact must map to a source
- Claims must include confidence and claim type
- Unsupported claims should fail or warn before final report generation

### Phase 5 — Report generation

Generate structured reports from the evidence ledger.

Initial templates:

- Company Brief
- Industry Primer
- Meeting Prep Brief
- Investment Memo

### Phase 6 — QA / red-team review

Add an explicit quality pass.

Required checks:

- unsupported claims
- weak sources
- stale sources
- missing risks
- missing competitors
- missing source appendix
- report not aligned with charter

### Phase 7 — Specialist agents

Only after the core workflow works, add specialists:

- Industry Agent
- Competitor Agent
- Financial Agent
- News Agent
- Risk Agent
- Filings Agent

## Project structure

```text
agentic-research-framework/
├── README.md
├── AGENTS.md
├── PROJECT_PLAN.md
├── ARCHITECTURE.md
├── IMPLEMENTATION_PHASES.md
├── CODEX_KICKOFF_PROMPT.md
├── CODEX_PHASE_PROMPTS.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── Makefile
├── configs/
├── docs/
├── prompts/
├── schemas/
├── templates/
├── examples/
├── src/
│   └── agentic_research/
├── tests/
└── runs/
```

## Local setup

Use the Makefile workflow so the `src/` layout is installed correctly and the
`arf` console script is verified.

First-time setup:

```bash
make reset-env
make doctor
make check
```

After switching branches:

```bash
make setup
make doctor
```

If `ModuleNotFoundError: No module named 'agentic_research'` appears, rebuild
the local environment:

```bash
make reset-env
make doctor
```

Run the deterministic CLI smoke test:

```bash
make smoke-mock
```

For live checkpoint smoke testing, copy `.env.example` to `.env`, add
`OPENAI_API_KEY` manually, and run:

```bash
make smoke-live-checkpoint
```

See `docs/LOCAL_DEVELOPMENT.md` for the full local setup, diagnosis, and
validation workflow.

The package uses a `src/` layout (`src/agentic_research/`), so local development
should use the editable install from `make setup` or `make reset-env` instead of
relying on `PYTHONPATH=src`.

Legacy manual setup commands:

```bash
mkdir agentic-research-framework
cd agentic-research-framework
git init

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

Install dependencies after Codex creates the package:

```bash
pip install -e ".[dev]"
```

Create environment file:

```bash
cp .env.example .env
```

## Codex workflow

1. Copy this starter kit into the repo.
2. Start Codex from the repo root.
3. Paste the full contents of `CODEX_KICKOFF_PROMPT.md`.
4. Require Codex to run tests before moving to the next phase.
5. Commit after every working phase.

Recommended loop:

```bash
pytest
arf run "Research Nvidia before an investor meeting" --mock --checkpoint-only
git status
git add .
git commit -m "Implement phase 1 mock research workflow"
```

## What not to build first

Do not build these in the first pass:

- Web app
- Database
- Authentication
- Background jobs
- PDF export
- Vector database
- Scheduled monitoring
- Complex SEC parser
- Private document ingestion

Build the smallest reliable research loop first.

## Reliability rule

The system should never treat unsupported fluent prose as research. The final report should be based on an evidence ledger, not on untracked model memory.

Every important factual claim should be traceable to:

- a source
- a source type
- a confidence level
- a report section
- a source URL or source id
