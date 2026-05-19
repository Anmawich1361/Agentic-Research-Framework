# Source Diversity Rubric

Checks whether reports use enough distinct source IDs for the scenario.

Pass criteria:
- Distinct claim source IDs meet `expected_qa.min_source_count`.
- Sources include appropriate source types for the fixture scenario.
- Evidence does not rely only on one company-controlled source unless caveated.

Common failures:
- All claims cite one source.
- Source appendix lists unused sources.
- Low-authority sources carry high-confidence claims.
