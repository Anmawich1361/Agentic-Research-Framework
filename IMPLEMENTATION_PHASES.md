# Implementation Phases

## Phase 1 — Deterministic skeleton

### Goal

Create a working local CLI app without live model calls.

### Build

- package structure
- CLI command
- config loader
- prompt loader
- Pydantic models
- deterministic source scoring
- evidence ledger class
- checkpoint writer
- mock orchestrator
- pytest suite

### Acceptance criteria

Command works:

```bash
arf run "Research Nvidia before an investor meeting" --mock --checkpoint-only
```

Artifacts created:

```text
runs/<run_id>/metadata.json
runs/<run_id>/charter.json
runs/<run_id>/source_map.json
runs/<run_id>/checkpoint.md
```

Tests pass:

```bash
pytest
```

## Phase 2 — Agents SDK integration

### Goal

Add live agents while preserving mock mode.

### Build

- agent factory
- prompt loading for agent instructions
- Intake Agent
- Planner Agent
- Source Discovery Agent
- Synthesis Agent
- QA Agent
- structured output parsing

### Acceptance criteria

Command works:

```bash
arf run "Research Costco before a supplier meeting" --checkpoint-only
```

Tests still mock live calls.

## Phase 3 — Source discovery tooling

### Goal

Improve source discovery quality.

### Build

- web search wrapper
- source candidate model
- source classification
- source map writer
- raw source candidate storage

### Acceptance criteria

The checkpoint contains:

- primary sources
- industry sources
- competitor sources
- news sources
- source gaps
- bias warnings

## Phase 4 — Evidence ledger workflow

### Goal

Track evidence before writing reports.

### Build

- evidence extraction prompt
- evidence claim model
- evidence ledger validator
- unsupported-claim warnings
- confidence levels

### Acceptance criteria

Full run creates:

```text
runs/<run_id>/evidence_ledger.json
```

Validation catches:

- fact claim without source
- high-confidence claim from low-authority source
- missing source id or URL

## Phase 5 — Report generation

### Goal

Generate useful markdown reports from evidence.

### Build

- report templates
- synthesis prompt
- source appendix builder
- markdown renderer

### Acceptance criteria

Full run creates:

```text
runs/<run_id>/draft_report.md
runs/<run_id>/report.md
```

Report includes:

- executive summary
- findings
- risks
- open questions
- questions to ask
- source appendix

## Phase 6 — QA review

### Goal

Add quality control before final delivery.

### Build

- QA Agent
- deterministic QA validators
- report status
- `needs_review` status for high-severity issues

### Acceptance criteria

Full QA run creates:

```text
runs/<run_id>/qa_review.json
```

High-severity issues prevent auto-finalization.

## Phase 7 — Specialist agents

### Goal

Add specialist research depth.

### Build order

1. Industry Agent
2. Competitor Agent
3. News Agent
4. Risk Agent
5. Financial Agent
6. Filings Agent

### Acceptance criteria

The orchestrator selects specialists based on research lens and target type.

## Phase 8 — v1 polish

### Goal

Make the system usable repeatedly.

### Build

- better CLI output
- examples
- improved README
- logging
- run listing
- rerun from checkpoint
- export options
- better errors

### Acceptance criteria

A user can run multiple research tasks and inspect saved artifacts without reading code.
