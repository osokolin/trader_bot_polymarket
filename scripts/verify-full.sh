#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
PIP_BIN="$PROJECT_ROOT/.venv/bin/pip"
BOT_BIN="$PROJECT_ROOT/.venv/bin/bot"

echo "==> Running full verification"

echo "==> Installing package in editable mode"
if ! "$PIP_BIN" install -e .; then
  echo "Editable install unavailable; falling back to workspace import check"
  PYTHONPATH="$PROJECT_ROOT" "$PYTHON_BIN" -c "import bot; print('workspace import OK')"
fi

echo "==> Unit tests"
"$PYTHON_BIN" -m unittest discover -s tests -v

echo "==> Syntax check"
"$PYTHON_BIN" -m py_compile $(find bot tests -name '*.py' | sort)

echo "==> Config validation"
"$BOT_BIN" config validate

echo "==> Demo seed workflow"
"$BOT_BIN" demo seed

echo "==> Full verification completed successfully"
