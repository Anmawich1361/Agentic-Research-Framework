.PHONY: install test lint typecheck check mock-run clean

install:
	pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check .

typecheck:
	mypy src

check: test lint typecheck

mock-run:
	arf run "Research Nvidia before an investor meeting" --mock --checkpoint-only

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache dist build *.egg-info
