#!/usr/bin/env bash
set -euo pipefail

echo "==> Running full verification"

echo "==> Installing package in editable mode"
pip install -e .

echo "==> Unit tests"
python -m unittest discover -s tests -v

echo "==> Syntax check"
python -m py_compile $(find bot tests -name '*.py' | sort)

echo "==> Config validation"
bot config validate

echo "==> Demo seed workflow"
bot demo seed

echo "==> Full verification completed successfully"