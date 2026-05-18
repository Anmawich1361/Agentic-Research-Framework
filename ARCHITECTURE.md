# Architecture

## System layers

```text
1. CLI / user interface
2. Orchestrator
3. Agent layer
4. Tool layer
5. Source scoring and evidence ledger
6. Artifact storage
7. Report writer
8. QA layer
```

## The orchestrator

The orchestrator is the central workflow controller. It should be mostly deterministic Python code.

Responsibilities:

- create run id
- load config
- run agents in sequence
- validate structured outputs
- call scoring functions
- write artifacts
- enforce checkpoint mode
- enforce QA status

Pseudo-flow:

```python
def run_research(request, mode, lens, checkpoint_only, full, qa, mock):
    run = create_run()
    charter = intake(request, mode=mode, lens=lens, mock=mock)
    plan = create_plan(charter, mock=mock)
    sources = discover_sources(plan, mock=mock)
    source_map = score_and_filter_sources(sources)
    checkpoint = write_checkpoint(charter, plan, source_map)

    if checkpoint_only:
        return checkpoint

    evidence = extract_evidence(charter, plan, source_map, mock=mock)
    draft = synthesize_report(charter, source_map, evidence, mock=mock)

    if qa:
        qa_review = run_qa(charter, source_map, evidence, draft, mock=mock)
        final = revise_or_mark_needs_review(draft, qa_review)
    else:
        final = draft

    return final
```

## Agent layer

An agent is:

```text
instructions + model + tools + output schema
```

### Initial agents

| Agent | Purpose | Output |
|---|---|---|
| Intake Agent | Understand request and user intent | ResearchCharter |
| Planner Agent | Convert charter into research questions and sections | ResearchPlan |
| Source Discovery Agent | Find and classify candidate sources | SourceCandidate[] |
| Research Manager Agent | Coordinate high-level reasoning when needed | Structured notes or manager decision |
| Synthesis Agent | Produce report from evidence | Markdown or Report object |
| QA Agent | Review report and evidence | QAReview |

### Specialist agents for later

| Agent | Use when |
|---|---|
| Industry Agent | industry primer, market structure, value chain |
| Competitor Agent | competitor maps, substitutes, positioning |
| Financial Agent | public-company financials, margins, growth, KPIs |
| News Agent | recent developments, leadership changes, M&A, lawsuits |
| Risk Agent | business, regulatory, legal, technology, customer risk |
| Filings Agent | 10-K, 10-Q, S-1, proxy, investor deck analysis |

## Tool layer

Start with wrappers, not complex scraping.

Initial tools:

- web search wrapper
- local file loader
- source URL collector
- simple URL metadata extractor
- optional SEC URL helper

Future tools:

- SEC filing fetcher
- document downloader
- PDF parser
- vector store ingestion
- company website crawler
- news API integration

## Source scoring

Source scoring should be deterministic code. Agents can propose classifications, but code should enforce scores.

Score dimensions:

- authority_score: 1-5
- relevance_score: 1-5
- recency_score: 1-5
- bias_risk: low, medium, high
- coverage_score: 1-5
- final_score: weighted calculation

## Evidence ledger

The evidence ledger is a reliability layer.

Reports should be written from the evidence ledger, not from raw model memory.

Required fields:

- id
- claim
- claim_type
- source_id
- source_title
- source_url
- source_type
- confidence
- report_section
- quote_or_excerpt
- created_at

## Artifact storage

Use local JSON and markdown first.

```text
runs/<run_id>/
├── metadata.json
├── charter.json
├── research_plan.json
├── sources.json
├── source_map.json
├── checkpoint.md
├── evidence_ledger.json
├── draft_report.md
├── qa_review.json
└── report.md
```

## Testing strategy

Tests should avoid live API calls.

Test categories:

- prompt loading
- config loading
- schema validation
- source scoring
- evidence ledger validation
- markdown writer
- mock orchestrator
- deterministic QA checks

## Why not one giant agent

A single agent can produce fluent output, but it is difficult to test and audit.

The research framework should separate:

- workflow control
- source discovery
- source quality
- evidence extraction
- writing
- QA

This makes the system faster to debug and safer to extend.
