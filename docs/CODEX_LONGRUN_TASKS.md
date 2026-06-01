# Long-Running Codex Tasks

This repository supports long-running Codex development goals when the user
explicitly asks for them. A goal can cover multiple edits, debugging loops,
verification passes, and documentation updates as long as the work stays inside
the stated scope.

## When Long-Running Work Is Allowed

Codex should keep working when the user says things like:

- "use the goal command"
- "complete the next unfinished milestone"
- "keep working until the validation bundle passes"
- "fix this end to end"
- "finish the roadmap item"

These requests authorize an extended development session. They do not authorize
unrelated product expansion.

## How To Execute

- Read the relevant roadmap, status doc, issue, or user prompt before changing
  files.
- Break the work into small, reviewable patches while continuing toward the
  larger outcome.
- Run focused checks after risky changes and broader checks before calling the
  goal complete.
- Report concrete command results and important artifact paths.
- Preserve generated run artifacts under `runs/<run_id>/` only when they are
  part of the requested validation or research workflow.
- Keep `.env`, `.venv`, cache files, and generated run artifacts out of commits
  unless the user explicitly asks otherwise.

## When To Stop

Stop only when one of these is true:

- the stated goal is complete and validation evidence has been reported,
- credentials, network access, or an external service are required and missing,
- the next step needs approval because it is destructive or privileged,
- repo state makes the scope ambiguous in a way local inspection cannot resolve,
- the user changes direction or asks Codex to pause.

Do not stop only because the work is long, because the first patch is complete,
or because one validation attempt failed. Failed validation is usually part of
the debugging loop.

## Product Boundaries Still Apply

Long-running Codex work is not a request to add product infrastructure outside
the repository's stated scope. The existing non-goals still apply unless the
user explicitly overrides them:

- no web app
- no database
- no authentication
- no background job system
- no scheduler
- no vector database
- no PDF or DOCX export workflow
- no complex SEC parser

The ARF product can still pause at a research checkpoint. That checkpoint is a
feature of the research workflow, not a reason for Codex to stop development
work before the requested implementation or validation goal is complete.
