# Evaluation

The Phase 12 evaluation harness provides repeatable local checks for research output quality.

Run:

```bash
python evals/run_eval.py
```

The default eval path is deterministic and does not call live APIs. It loads fixture source maps, evidence ledgers, and draft reports, then checks:

- source grounding
- evidence depth
- report usefulness
- unsupported claims
- source diversity
- recency handling

Fixtures are stored in `evals/fixtures/`. Rubric descriptions are stored in `evals/rubrics/`.

The runner exits non-zero when a fixture fails. Failure output lists the fixture and the specific failed checks, so regressions are readable and actionable.
