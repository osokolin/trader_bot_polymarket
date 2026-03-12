#!/usr/bin/env bash
set -euo pipefail

echo "==> Running fast verification"

echo "==> Unit tests"
python -m unittest discover -s tests -v

echo "==> Syntax check"
python -m py_compile $(find bot tests -name '*.py' | sort)

echo "==> Fast verification completed successfully"