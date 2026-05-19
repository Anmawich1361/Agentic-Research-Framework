#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "Removing .venv"
rm -rf .venv

echo "Creating .venv with python3"
python3 -m venv .venv

echo "Upgrading pip, setuptools, and wheel"
.venv/bin/python -m pip install --upgrade pip setuptools wheel

echo "Installing agentic-research-framework in editable mode with dev extras"
.venv/bin/python -m pip install -e ".[dev]"

echo "Environment reset complete. Run 'make doctor' next."
