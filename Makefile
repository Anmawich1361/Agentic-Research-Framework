VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_PYTEST := $(VENV)/bin/pytest
VENV_RUFF := $(VENV)/bin/ruff
VENV_MYPY := $(VENV)/bin/mypy
ARF := $(VENV)/bin/arf

.PHONY: setup reset-env doctor check smoke-mock smoke-live-checkpoint eval eval-regression install test pytest-smoke lint typecheck mock-run clean ensure-venv

setup:
	@if [ ! -x "$(VENV_PYTHON)" ]; then \
		echo "Creating $(VENV) with python3"; \
		python3 -m venv "$(VENV)"; \
	fi
	@$(VENV_PYTHON) -m pip --version >/dev/null 2>&1 || ( \
		echo "pip is not usable in $(VENV). Run 'make reset-env' to rebuild it." >&2; \
		exit 1; \
	)
	$(VENV_PYTHON) -m pip install --upgrade pip setuptools wheel
	$(VENV_PYTHON) -m pip install -e ".[dev]"

reset-env:
	./scripts/reset_env.sh

doctor: ensure-venv
	$(VENV_PYTHON) scripts/doctor_env.py

ensure-venv:
	@test -x "$(VENV_PYTHON)" || ( \
		echo "Missing $(VENV). Run 'make setup' or 'make reset-env'." >&2; \
		exit 1; \
	)

test: ensure-venv
	PYTHONPATH=$(CURDIR) $(VENV_PYTEST)

pytest-smoke: ensure-venv
	$(VENV_PYTEST) --version

lint: ensure-venv
	$(VENV_RUFF) check .

typecheck: ensure-venv
	$(VENV_MYPY) src

check: test lint typecheck

eval: ensure-venv
	$(VENV_PYTHON) evals/run_eval.py

eval-regression: ensure-venv
	$(VENV_PYTHON) evals/run_regression.py

smoke-mock: ensure-venv
	$(ARF) run "Research Nvidia before an investor meeting" --mock --checkpoint-only

smoke-live-checkpoint: ensure-venv
	./scripts/load_env_and_run.sh $(ARF) run "Research Costco before a supplier meeting" --checkpoint-only --mode brief --lens sales

install: setup

mock-run: smoke-mock

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache dist build *.egg-info
