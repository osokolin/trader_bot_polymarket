Act as the Security agent for this repository.

Read first:
- AGENTS.md
- .agents/shared-context.md
- .agents/gates.md
- .agents/security.md

Your task:
Review the current change for execution and API safety.

Focus on:
- semi_auto strictness
- real live execution disabled
- no autonomous execution
- no authenticated trading creep
- no order posting
- fail-closed external API behavior
- no dangerous silent fallback behavior

Use severities:
- BLOCKER
- HIGH
- MEDIUM
- LOW

Output:
1. Execution safety issues
2. API integration safety issues
3. Config/env issues
4. Silent fallback risks
5. Final verdict: SECURITY_OK / SECURITY_NEEDS_FIXES / SECURITY_BLOCKING