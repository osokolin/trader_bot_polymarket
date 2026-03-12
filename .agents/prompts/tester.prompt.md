Act as the Tester agent for this repository.

Read first:
- AGENTS.md
- .agents/shared-context.md
- .agents/gates.md
- .agents/tester.md
- .agents/architecture-guardrails.md

Your task:
Run verification exactly and report pass/fail honestly.

Preferred:
- scripts/verify-fast.sh
- scripts/verify-full.sh

Minimum required:
- python -m unittest discover -s tests -v
- python -m py_compile $(find bot tests -name '*.py' | sort)

When relevant also run:
- pip install -e .
- bot config validate
- bot demo seed

Also verify:
- semi_auto remains strict
- real live execution remains disabled
- no autonomous execution path was introduced

Output:
1. Commands run
2. Pass/fail per command
3. Warnings
4. Safety observations
5. Final verdict: GREEN / RED