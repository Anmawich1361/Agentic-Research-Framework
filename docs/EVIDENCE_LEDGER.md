# Evidence Ledger

## Purpose

The evidence ledger prevents unsupported claims from entering the final report.

The system should treat the ledger as the factual substrate for the report.

## Claim types

| Claim type | Meaning |
|---|---|
| fact | Directly supported by a source |
| inference | Reasonable interpretation based on multiple facts |
| opinion | Source or analyst opinion |
| unknown | Needs review |

## Confidence levels

| Confidence | Meaning |
|---|---|
| high | Strong source, direct support, recent enough |
| medium | Reasonable support but some limitation |
| low | Weak, indirect, stale, or partial support |

## Required fields

```json
{
  "id": "claim_001",
  "claim": "The company sells field service management software.",
  "claim_type": "fact",
  "source_id": "source_001",
  "source_title": "Company product page",
  "source_url": "https://example.com",
  "source_type": "company_website",
  "confidence": "medium",
  "report_section": "Business Overview",
  "quote_or_excerpt": null
}
```

## Validation rules

- A fact must have a source id or source URL.
- Claim IDs must be unique before synthesis. Identical duplicates are deduplicated
  deterministically, conflicting base evidence IDs block synthesis, and conflicting
  specialist evidence IDs are renamed with a stable specialist prefix.
- A high-confidence fact should come from a high-authority source.
- A claim based only on company marketing should not be overstated.
- Inferences should be labeled as inferences.
- Unknown claims should not appear in the final report unless explicitly flagged.
