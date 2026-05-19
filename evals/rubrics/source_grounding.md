# Source Grounding Rubric

Checks whether report claims trace to known evidence claim IDs and known source IDs.

Pass criteria:
- No high-severity deterministic QA issue in `unsupported_claim` or `source_gap`.
- Every material report claim cites an evidence claim ID.
- Source appendix entries use source IDs present in the fixture source map.

Common failures:
- Citing claim IDs not present in the evidence ledger.
- Referencing source IDs not present in the source map.
- Making uncited broad claims in report prose.
