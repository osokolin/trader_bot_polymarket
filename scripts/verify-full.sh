#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
BOT_BIN="$PROJECT_ROOT/.venv/bin/bot"

echo "==> Running full verification"

echo "==> Canonical fast verification"
"$PROJECT_ROOT/scripts/verify-fast.sh"

echo "==> Config validation"
"$BOT_BIN" config validate

echo "==> Demo seed workflow"
"$BOT_BIN" demo seed

echo "==> Full verification completed successfully"
