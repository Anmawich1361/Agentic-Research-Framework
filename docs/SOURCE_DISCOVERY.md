# Source Discovery

## Goal

Find the best available sources before deep synthesis.

The source discovery agent should not write the final report. It should collect, classify, and explain sources.

## Source categories

| Category | Examples | Notes |
|---|---|---|
| primary_company | company website, press releases, product pages | Useful but biased |
| corporate_filing | 10-K, 10-Q, S-1, proxy | High authority for public companies |
| investor_material | earnings presentation, investor day deck | Useful but management-framed |
| earnings_transcript | quarterly calls | Good for recent priorities |
| government_data | BLS, Census, FRED, SEC | Usually high authority |
| industry_primer | consulting report, association report | Good for structure and vocabulary |
| competitor_source | competitor websites, filings | Needed for landscape |
| news | Reuters, FT, WSJ, trade publications | Useful for recent developments |
| whitepaper | vendor or technical report | Often biased but useful for context |
| expert_blog | analyst blog, newsletter | Variable quality |

## Source map requirements

A source map should include:

- strongest sources
- source type
- score
- confidence
- bias risk
- recommended use
- gaps
- rejected or downgraded sources when relevant

## Company-source priority

For company targets, source discovery starts with bounded primary-source
queries before broad web coverage:

- direct SEC 10-K filing pages
- official company pages
- investor relations and investor presentations
- earnings releases and earnings transcripts

Per-query search failures are non-fatal. They should be preserved in
`source_map.gaps` instead of aborting the checkpoint.

## Retrieval fallback boundary

Source ingestion may repair stale SEC archive URLs and try a small set of
official company fallback URLs. It should not become a complex SEC parser, and
failed, skipped, or fallback-only source fetches must stay visible in
`source_fetch_log.json`.
