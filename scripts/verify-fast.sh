#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"

echo "==> Running fast verification"

echo "==> Tests"
"$PYTHON_BIN" -m pytest

echo "==> Lint"
"$PYTHON_BIN" -m ruff check bot tests scripts

echo "==> Type check"
"$PYTHON_BIN" -m mypy

echo "==> Syntax check"
"$PYTHON_BIN" -m py_compile $(find bot tests -name '*.py' | sort)

echo "==> Fast verification completed successfully"
