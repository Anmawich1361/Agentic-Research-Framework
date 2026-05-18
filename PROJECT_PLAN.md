# Project Plan

## Objective

Build an agentic research system that prepares company and industry research before the user begins their own manual review.

The system should be useful for:

- company briefings
- industry primers
- sales meeting prep
- investment research
- job interview prep
- competitor analysis
- diligence-style research

## Product principle

The application is a workflow controller with agents inside it. It is not one large prompt.

The workflow controller owns:

- phase ordering
- run state
- checkpointing
- source scoring
- evidence ledger validation
- artifact writing
- report status
- testability

Agents own:

- interpretation
- summarization
- source discovery assistance
- evidence extraction
- synthesis
- QA review

## User journey

### 1. User request

Example:

```text
Research ServiceTitan before my sales meeting next week.
```

### 2. Intake

The system identifies:

- target: ServiceTitan
- target type: company
- lens: sales
- depth: brief or standard
- deliverable: meeting prep brief
- geography: default from context or global/US
- time horizon: current plus recent developments

### 3. Research charter

The system creates a structured charter:

```json
{
  "target": "ServiceTitan",
  "target_type": "company",
  "research_lens": "sales",
  "depth": "brief",
  "deliverable": "meeting_prep_brief",
  "key_questions": [
    "What does the company do?",
    "Who are its customers?",
    "What are its likely priorities?",
    "Who are its competitors?",
    "What should the user ask in the meeting?"
  ]
}
```

### 4. Source discovery

The system finds candidate sources:

- corporate website
- product pages
- press releases
- filings, if public
- investor decks, if available
- competitor websites
- industry primers
- trade publications
- news
- government or market data sources

### 5. Source scoring

Each source is scored by:

- relevance
- authority
- recency
- bias risk
- coverage

### 6. User checkpoint

The system pauses and shows:

- research charter
- initial source map
- early read
- source gaps
- proposed report angle
- questions for user steering

### 7. Deep research

After approval, the system extracts evidence and runs analysis agents.

### 8. Evidence ledger

Each important claim is tracked.

Required fields:

- claim
- claim type
- source title
- source URL or id
- source type
- confidence
- report section
- optional excerpt

### 9. Synthesis

The report is generated from the evidence ledger, not from unsupported freeform context.

### 10. QA

A QA agent and deterministic validators check:

- unsupported facts
- missing citations
- weak sources
- stale sources
- missing risks
- missing competitors
- unaddressed user purpose

### 11. Final report

The report includes:

- executive summary
- core findings
- risks
- open questions
- questions to ask
- source appendix

## MVP definition

The first usable MVP is complete when the app can:

1. Accept a user research request from the CLI.
2. Generate a research charter.
3. Discover and score sources.
4. Produce a checkpoint.
5. Save artifacts under `runs/<run_id>/`.
6. Run in `--mock` mode without API calls.
7. Pass deterministic tests.

## v1 definition

The first strong v1 is complete when the app can:

1. Run live agents.
2. Use web search for source discovery.
3. Extract evidence claims.
4. Generate a cited markdown report.
5. Run QA checks.
6. Save all artifacts.
7. Preserve source traceability.
8. Keep tests deterministic by mocking live calls.

## Design constraints

- Keep the first version local and CLI-first.
- Use local JSON artifacts before introducing a database.
- Use markdown reports before PDF or DOCX exports.
- Keep the workflow deterministic where possible.
- Add specialist agents only after the core pipeline works.
- Do not allow reports to rely on untracked model claims.

## Success criteria

A successful report should be:

- aligned with the user's purpose
- grounded in strong sources
- explicit about uncertainty
- clear about facts vs analysis
- useful for a real meeting, memo, or decision
- easy to audit through the evidence ledger
