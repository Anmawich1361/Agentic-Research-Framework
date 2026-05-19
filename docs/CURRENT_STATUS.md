# Current Status

This note records the stabilization point after PR #5 and PR #6.

## Recent Merges

PR #5 implemented phases 9-14 in one large merge. It added or hardened the
quality-focused parts of the pipeline: evidence quality review, source ingestion,
artifact review, report validation, QA structure, and production-readiness docs.

PR #6 fixed stale claim-reference integrity. Synthesis now receives
`allowed_claim_ids` from the final evidence ledger after deduplication,
evidence-quality filtering, specialist merge, and claim-ID renaming. Pre-QA
validation now catches unknown claim references before QA and writes a clear
draft-revision diagnostic.

Both merges are kept. This stabilization pass focuses on documentation and
artifact contracts before adding more research features.

## Current Blocker

The current blocker is content quality, not claim-ID integrity.

The latest live full QA path can reach synthesis and QA without unknown evidence
claim references. QA can still block publication when the report overstates
evidence, lacks recent Costco-specific support, or presents inferred supplier
priorities too confidently.

## Publication Gate

Final report publication remains QA-gated.

The framework writes `report.md` only when:

- the workflow is run with `--qa`,
- deterministic pre-QA report validation passes,
- QA runs,
- no high-severity QA issues remain.

Blocked runs retain review artifacts such as `draft_report.md`,
`qa_review.json`, `report_revision.md`, `evidence_review.md`, or
`artifact_review.md` as applicable.
