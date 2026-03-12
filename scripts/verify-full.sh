#!/usr/bin/env bash
set -euo pipefail

echo "==> Running full verification"

echo "==> Installing package in editable mode"
.venv/bin/pip install -e .

echo "==> Unit tests"
.venv/bin/python -m unittest discover -s tests -v

echo "==> Syntax check"
.venv/bin/python -m py_compile $(find bot tests -name '*.py' | sort)

echo "==> Config validation"
.venv/bin/bot config validate

echo "==> Demo seed workflow"
.venv/bin/bot demo seed

echo "==> Full verification completed successfully"