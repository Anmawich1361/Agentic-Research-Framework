# Live Smoke and Artifact Review Playbook

Use this after each live checkpoint, full, or full+QA run.

---

# 1. Baseline environment

```bash
git checkout main
git pull
make doctor
make check
```

---

# 2. Live checkpoint

```bash
make smoke-live-checkpoint
```

Inspect:

```bash
RUN_ID="paste_run_id"

ls -la "runs/$RUN_ID"
cat "runs/$RUN_ID/metadata.json"
cat "runs/$RUN_ID/checkpoint.md"
python -m json.tool "runs/$RUN_ID/source_map.json" | head -240
```

Expected:

- `mock: false`
- `status: checkpoint_ready`
- checkpoint uses live wording
- sources have real URLs
- gaps are plausible, not noisy false positives

---

# 3. Live full without QA

```bash
./scripts/load_env_and_run.sh .venv/bin/arf run "Research Costco before a supplier meeting" --full --mode brief --lens sales
```

Expected:

- `draft_report.md` exists if synthesis occurs
- `report.md` does not exist
- status is `draft_needs_qa`, `draft_needs_revision`, or `evidence_needs_review`

Inspect:

```bash
RUN_ID="paste_run_id"

ls -la "runs/$RUN_ID"
cat "runs/$RUN_ID/metadata.json"
python -m json.tool "runs/$RUN_ID/evidence_ledger.json" | head -240
cat "runs/$RUN_ID/draft_report.md"
```

---

# 4. Live full with QA

```bash
./scripts/load_env_and_run.sh .venv/bin/arf run "Research Costco before a supplier meeting" --full --qa --mode brief --lens sales
```

Inspect:

```bash
RUN_ID="paste_run_id"

ls -la "runs/$RUN_ID"
cat "runs/$RUN_ID/metadata.json"

if [ -f "runs/$RUN_ID/evidence_review.md" ]; then
  cat "runs/$RUN_ID/evidence_review.md"
fi

if [ -f "runs/$RUN_ID/evidence_ledger.json" ]; then
  python -m json.tool "runs/$RUN_ID/evidence_ledger.json" | head -240
fi

if [ -f "runs/$RUN_ID/qa_review.json" ]; then
  python -m json.tool "runs/$RUN_ID/qa_review.json" | head -240
fi

if [ -f "runs/$RUN_ID/report.md" ]; then
  echo "Final report exists"
  cat "runs/$RUN_ID/report.md"
elif [ -f "runs/$RUN_ID/draft_report.md" ]; then
  echo "No final report; showing draft"
  cat "runs/$RUN_ID/draft_report.md"
else
  echo "No draft_report.md or report.md"
fi
```

---

# 5. Status interpretation

| Status | Meaning | Next action |
|---|---|---|
| `checkpoint_ready` | checkpoint complete | user steering or full run |
| `evidence_needs_review` | evidence blocked synthesis | inspect `evidence_review.md` |
| `draft_needs_revision` | synthesis draft missing structural requirements | repair report/template prompts |
| `draft_needs_qa` | draft exists but QA not run | run `--full --qa` |
| `needs_review` | QA blocked final report | inspect `qa_review.json` |
| `report_ready` | final report written | inspect quality before trusting |

---

# 6. Artifact quality checklist

## Source map

- Are sources authoritative?
- Are there enough non-company sources?
- Are gaps meaningful?
- Are there future-dated or questionable sources?
- Are source types canonical?

## Evidence ledger

- Are claims substantive?
- Are claim IDs unique?
- Are near duplicates present?
- Are high-confidence claims justified?
- Are source IDs valid?
- Are quote excerpts actual source content or just snippets?

## Specialist analysis

- Does it add value or repeat the base evidence?
- Does it introduce unsupported facts?
- Are specialist claims source-bound?

## Draft report

- Does it answer the user's purpose?
- Does every material assertion cite claim IDs?
- Are inferences clearly labeled?
- Does it admit evidence limitations?
- Are recommendations actionable?

## QA review

- Are high-severity issues legitimate?
- Are suggested fixes specific?
- Are issues categorized?
- Does QA explain why final publication was blocked?

---

# 7. Cleanup

Do not commit run artifacts.

```bash
git status
find runs -mindepth 1 ! -name ".gitkeep" -exec rm -rf {} +
git status
```
