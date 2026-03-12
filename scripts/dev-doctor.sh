#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$PROJECT_ROOT/.venv"
PY="$VENV/bin/python"
BOT="$VENV/bin/bot"

ok() {
  echo "[OK]   $1"
}

warn() {
  echo "[WARN] $1"
}

fail() {
  echo "[FAIL] $1"
}

section() {
  echo ""
  echo "==> $1"
}

overall_failed=0

run_check() {
  local label="$1"
  shift
  if "$@" >/tmp/trader_bot_doctor.out 2>/tmp/trader_bot_doctor.err; then
    ok "$label"
  else
    fail "$label"
    cat /tmp/trader_bot_doctor.err >/dev/null 2>&1 || true
    overall_failed=1
  fi
}

section "Doctor check"

# 1. venv / python
if [ -x "$PY" ]; then
  ok "Python venv"
else
  fail "Python venv (.venv/bin/python not found)"
  exit 1
fi

# 2. package import sanity
if "$PY" -c "import bot" >/dev/null 2>&1; then
  ok "Package import"
else
  fail "Package import"
  overall_failed=1
fi

# 3. config validate
if "$BOT" config validate >/tmp/trader_bot_doctor.out 2>/tmp/trader_bot_doctor.err; then
  ok "Config validation"
else
  fail "Config validation"
  overall_failed=1
fi

# 4. diagnostics polymarket
# assumes you already implemented:
#   bot diagnostics polymarket
if "$BOT" diagnostics polymarket >/tmp/trader_bot_doctor.out 2>/tmp/trader_bot_doctor.err; then
  ok "Polymarket diagnostics"
else
  fail "Polymarket diagnostics"
  overall_failed=1
fi

# 5. scanner smoke
# read-only smoke to ensure command path is wired
if "$BOT" markets scan --limit 1 >/tmp/trader_bot_doctor.out 2>/tmp/trader_bot_doctor.err; then
  ok "Scanner wiring"
else
  fail "Scanner wiring"
  overall_failed=1
fi

echo ""
if [ "$overall_failed" -eq 0 ]; then
  echo "Overall: HEALTHY"
  exit 0
else
  echo "Overall: NEEDS_ATTENTION"
  exit 1
fi