# Recency Handling Rubric

Checks whether recent context is verified or caveated.

Pass criteria:
- Fixtures requiring recent signals include at least one source with `publication_date`.
- Deterministic QA does not flag `missing_recent_signal` or `stale_or_unclear_recency`.
- Reports avoid claiming "recent" developments without a concrete dated source.

Common failures:
- Treating stale filings as current without caveat.
- Citing source discovery metadata instead of source content.
- Missing explicit recency limitations for thin source sets.
