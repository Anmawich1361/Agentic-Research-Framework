# Phase 8 Full QA Live Smoke

Date: 2026-05-18 local / 2026-05-19 UTC

Command:

```bash
./scripts/load_env_and_run.sh .venv/bin/arf run "Research Costco before a supplier meeting" --full --qa --mode brief --lens sales
```

## Run Summary

- Run ID: `run_20260519T013443Z_eff7e3fd`
- Status: `evidence_needs_review`
- Final report: not written
- Draft report: not written
- QA review: not written
- Artifact review: `runs/run_20260519T013443Z_eff7e3fd/artifact_review.md`

## Artifacts Produced

- `metadata.json`
- `charter.json`
- `research_plan.json`
- `sources.json`
- `source_map.json`
- `specialist_analyses.json`
- `evidence_ledger.json`
- `evidence_review.md`
- `checkpoint.md`
- `artifact_review.md`

## QA Blockers

QA did not run because evidence validation blocked synthesis first.

## Evidence-Quality Issues

- `C1` and `C2` are high-confidence fact claims without source IDs or URLs.
- `C1` and `C2` were classified as `unsupported_or_unclear`.
- `specialist_competitor_C5` and `R3` were classified as `source_finding_aid`.
- `R7` is a high-confidence claim backed by a lower-authority source.
- The evidence ledger has 33 claims, 33 unique claim IDs, and 0 near duplicates after deduplication.

## Recommended Next Fixes

1. Tighten evidence extraction so high-confidence fact claims must include direct source support.
2. Prevent source-finding-aid statements from entering the ledger as evidence claims.
3. Lower confidence or improve sourcing for claims backed by lower-authority news/search-result sources.
4. Rerun full+QA after evidence passes the pre-synthesis quality gate.
