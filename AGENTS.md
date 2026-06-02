# AGENTS.md

## Project

This repository is a Python CLI-first agentic research framework for company and industry research.

The system should:

1. Understand a user research request.
2. Create a research charter.
3. Discover and score sources.
4. Pause at a user checkpoint.
5. Run deeper research after approval.
6. Build an evidence ledger.
7. Generate a cited markdown report.
8. Run QA/red-team checks before final output.

## Repository authority

- `docs/PROJECT_COMPLETION_PLAN.md` is the roadmap and milestone scope authority.
- `README.md` should stay a concise project overview and command entrypoint.
- `docs/CURRENT_STATUS.md` should stay the latest implementation/status ledger.
- `docs/CODEX_LONGRUN_TASKS.md` holds detailed long-running Codex guidance.
- If those docs appear to conflict, inspect the current branch, current docs, and
  the user's prompt before changing scope. Ask only when local evidence cannot
  resolve the conflict.

## Start-of-session preflight

Before planning broad work, editing files, or diagnosing failures, ground the
session in the current repo state:

```bash
pwd
git status -sb
git branch --show-current
make doctor
```

Also check branch/upstream reality before PR or milestone work:

```bash
git rev-parse --abbrev-ref --symbolic-full-name @{u}
git status -sb
```

When publishing, first check whether a PR already exists for the head branch:

```bash
gh pr list --head "$(git branch --show-current)"
```

If a PR looks incomplete or conflicted, verify whether the branch was created
from a stale local `main` before redoing implementation. Rebase or compare
against current `origin/main` when branch ancestry is the real issue.

## Coding rules for Codex

- Do not implement the whole system in one giant file.
- Keep orchestration in Python code, not only inside prompts.
- Use Pydantic models for structured data.
- Keep tests deterministic.
- Do not make live OpenAI API calls in tests.
- Preserve `--mock` mode throughout the project.
- Save run artifacts under `runs/<run_id>/`.
- Every material factual claim in a report must map to an evidence ledger entry.
- Prefer small, reviewable changes.
- Do not silently remove files or prompts unless explicitly asked.
- Use type hints where practical.
- Avoid over-engineering early phases.
- Keep changes CLI-first, filesystem-first, and artifact-first unless the user
  explicitly changes product scope.
- Preserve evidence validation, report traceability, fallback-only evidence
  blocking, QA blocking behavior, and `report.md` publication gates.

## Long-running Codex goals

Long-running Codex work is allowed when the user explicitly starts a goal,
asks to finish a roadmap milestone, asks to keep working until validation
passes, or otherwise grants a broad execution scope.

- Treat an explicit goal as permission to continue across multiple
  implementation, debugging, documentation, and validation loops until the
  stated outcome is complete or genuinely blocked.
- Do not stop merely because the task spans many files, takes a long time, or
  requires several verification passes.
- "Prefer small, reviewable changes" means keep each change coherent and easy
  to inspect; it is not a reason to stop before the requested goal is complete.
- Product checkpoint rules apply to ARF research runs, not to Codex's own
  development workflow. If the user asks Codex to implement or validate work,
  continue without asking for intermediate approval unless scope, safety,
  credentials, or destructive operations require it.
- For long goals, leave clear progress notes in the conversation and preserve
  durable evidence in repo artifacts or docs when the task calls for it.
- Stop only for a true blocker: missing credentials, unavailable services,
  unclear or conflicting scope that cannot be resolved from repo context,
  approval needed for destructive or privileged operations, or exhausted user
  budget.
- Do not add product background jobs, scheduled automations, databases, or other
  excluded features just to support a long Codex session.

## Setup and environment repair

Use the Makefile targets instead of manually setting `PYTHONPATH`:

```bash
make reset-env
make doctor
make check
```

After switching branches, this is usually enough:

```bash
make setup
make doctor
```

Treat these symptoms as likely editable-install or `.venv` damage before
debugging application code:

- `ModuleNotFoundError: No module named 'agentic_research'`
- broken or missing `.venv/bin/arf`
- pytest collection failures caused by missing installed packages
- repeated missing-package errors after a targeted reinstall

Run `make doctor` first. If the environment is broadly damaged, use
`make reset-env` rather than piecemeal package repairs. Do not weaken tests,
imports, or CLI behavior to work around a broken local environment.

## Validation commands

For docs-only changes, run:

```bash
make doctor
./.venv/bin/python -m pytest tests/test_docs_contract.py
git diff --check
```

For milestone, workflow, or code changes, run:

```bash
make doctor
make check
make eval
make eval-regression
make smoke-mock
git diff --check
```

Use focused tests during development, but do not claim a milestone/code change
is complete until the relevant broader bundle has run and the results have been
reported command by command.

## PR and staging workflow

When the user says "make a PR", "open a PR", "publish this", or similar, treat
it as the full publish flow unless they explicitly ask for something narrower:

1. Check `git status -sb` and keep staging narrow.
2. Stage only intended source, test, prompt, config, schema, template, or doc
   files.
3. Commit with a concise message.
4. Push the current branch.
5. Open a draft PR against `main`.
6. Verify the PR with `gh pr view` or `gh pr list --head`.

Do not stage `.env`, `.venv`, caches, `runs/`, generated run artifacts,
generated demo exports, duplicate scratch docs such as `docs/* 2.md`, or
unrelated untracked files unless the user explicitly asks for them.

Do not merge a PR unless the user explicitly asks. If the GitHub connector fails
but local `gh` auth is valid, fall back to `gh pr create --draft` and verify the
created PR.

## ARF run success semantics

When answering whether ARF can research a company or whether a run "worked",
describe the outcome using `metadata.json.status` and the run artifacts rather
than unconditional success language.

- `report.md` means a final report was published after the configured gates.
- `artifact_review.md` summarizes missing/present artifacts, warning counts, and
  next actions.
- `evidence_review.md` means evidence validation blocked synthesis or
  publication.
- `qa_review.json` records QA findings when QA ran.
- `report_revision.md` means deterministic report validation found traceability
  or structure issues that need revision.

If live source access, evidence quality, or QA gates stop publication, report the
blocking artifact and next action instead of weakening gates or implying the
run produced a publishable report.

## CLI target

```bash
arf run "Research Nvidia before an investor meeting" --mock --checkpoint-only
```

## Architecture sequence

1. Intake
2. Research charter
3. Source discovery
4. Source scoring
5. User checkpoint
6. Deep research
7. Evidence ledger
8. Synthesis
9. QA review
10. Final report

## Do not build yet

Unless specifically requested, do not build:

- web app
- database
- authentication
- background jobs
- scheduled automations
- PDF or DOCX export
- vector database
- complex SEC parser

Stop rather than adding these excluded features to work around a CLI, artifact,
or local-environment issue.

## Test commands

The full `make check` target runs the standard local test bundle:

```bash
pytest
ruff check .
mypy src
```

## File conventions

- Agent prompts live in `prompts/agents/`.
- Research policies live in `prompts/policies/`.
- Workflow prompts live in `prompts/workflows/`.
- JSON schemas live in `schemas/`.
- YAML configuration lives in `configs/`.
- Report templates live in `templates/`.
- Saved run artifacts live in `runs/<run_id>/`.

## Testing expectations

Tests should cover:

- prompt loading
- config loading
- schema validation
- source scoring
- evidence ledger validation
- report writing
- mock orchestrator behavior

No test should require network access or an OpenAI API key.
