# Design Decisions

## Decision 1: CLI-first

The first version will be a local CLI application. This keeps the system fast to build and easier to test.

## Decision 2: Local JSON artifacts before database

All run artifacts are saved under `runs/<run_id>/`.

A database can be added later if repeated use creates a need for search, sharing, or long-term storage.

## Decision 3: Evidence ledger before final report

The system should not generate a final report from raw model context alone.

## Decision 4: Mock mode is mandatory

Mock mode makes the workflow testable without API calls.

## Decision 5: Specialist agents come later

Start with a manager-led flow. Add specialists only after the core checkpoint and evidence workflow is working.
