# Local Development

This project uses a `src/` layout: the importable package lives at
`src/agentic_research/`. That layout keeps packaging honest, but it also means
plain `python` from the repo root is not enough. Install the project in editable
mode so Python and the `arf` console script resolve the package through the
package metadata instead of a temporary `PYTHONPATH=src` workaround.

## First-Time Setup

```bash
make reset-env
make doctor
make check
```

`make reset-env` removes and recreates `.venv`, upgrades packaging tools, and
installs the project with dev extras in editable mode.

## After Switching Branches

```bash
make setup
make doctor
```

`make setup` creates `.venv` if it is missing and refreshes the editable install
without forcing a full environment rebuild.

## When Imports Break

If you see this error:

```text
ModuleNotFoundError: No module named 'agentic_research'
```

run:

```bash
make reset-env
make doctor
```

`make doctor` prints the active branch, Python executable, pip executable,
`sys.path`, the resolved `agentic_research.__file__`, and whether
`.venv/bin/arf --help` works. It also checks whether `.env` exists and reports
only boolean `OPENAI_API_KEY` status.

## Validation

```bash
make check
make smoke-mock
```

`make check` runs:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy src
```

`make smoke-mock` runs the deterministic checkpoint-only CLI path without live
API calls.

## Live Checkpoint Smoke Test

Create a local environment file:

```bash
cp .env.example .env
```

Edit `.env` manually and add `OPENAI_API_KEY`. Do not commit `.env`.

Then run:

```bash
make smoke-live-checkpoint
```

The live smoke target loads `.env` with a small `KEY=VALUE` parser, verifies
that `OPENAI_API_KEY` is present without printing it, and runs:

```bash
.venv/bin/arf run "Research Costco before a supplier meeting" --checkpoint-only --mode brief --lens sales
```
