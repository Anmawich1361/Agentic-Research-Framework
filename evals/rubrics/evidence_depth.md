# Evidence Depth Rubric

Checks whether a fixture has enough evidence claims for the requested report type.

Pass criteria:
- Fixture evidence claim count meets `expected_qa.min_claim_count`.
- Claims are substantive enough to support report sections.
- Thin source sets are explicitly caveated when used.

Common failures:
- One-source reports without an `Evidence Limitations` section.
- Evidence claims that describe a source artifact instead of research findings.
- Missing claim coverage for key report sections.
